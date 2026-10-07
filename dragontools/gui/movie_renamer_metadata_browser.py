# -*- coding: utf-8 -*-
"""Interactive TMDB/TheTVDB browser and explicit episode/file mapper."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QByteArray, QMimeData, QSettings, QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.path_syntax import is_video_file, path_compare_key
from ..core.renamer_metadata_browser import (
    ExplicitFileMapping,
    ExplicitMovieFileMapping,
    ExplicitSeriesFileMapping,
    MetadataBrowserEpisode,
    MetadataBrowserHit,
    RenamerMetadataBrowserService,
    dedupe_paths,
    natural_path_key,
)
from .drop_path_extractor import _extract_paths_from_mime_data, _mime_has_file_payload
from .drop_path_files import iter_video_files_in_folder
from .ui_helpers import install_persistent_window_geometry, save_window_geometry

from .movie_renamer_browser_mapping import RenamerBrowserMappingMixin
from .movie_renamer_browser_runtime import RenamerBrowserRuntimeMixin

_MAPPING_MIME = "application/x-dragontools-renamer-paths"


class _BrowserWorker(QThread):
    succeeded = pyqtSignal(int, object)
    failed = pyqtSignal(int, str)

    def __init__(self, token: int, fn: Callable[[], object], parent=None) -> None:
        super().__init__(parent)
        self.token = int(token)
        self.fn = fn

    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as exc:
            self.failed.emit(self.token, str(exc))
            return
        if not self.isInterruptionRequested():
            self.succeeded.emit(self.token, result)


class MetadataSourceList(QListWidget):
    paths_dropped = pyqtSignal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)

    def mimeData(self, items):  # noqa: N802 - Qt API
        mime = QMimeData()
        paths = [str(item.data(Qt.ItemDataRole.UserRole) or "") for item in items]
        paths = [path for path in paths if path]
        mime.setData(_MAPPING_MIME, QByteArray("\n".join(paths).encode("utf-8")))
        return mime

    def dragEnterEvent(self, event) -> None:
        mime = event.mimeData()
        if mime and (_mime_has_file_payload(mime) or mime.hasFormat(_MAPPING_MIME)):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        mime = event.mimeData()
        if mime and (_mime_has_file_payload(mime) or mime.hasFormat(_MAPPING_MIME)):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        paths = _extract_paths_from_mime_data(event.mimeData())
        if paths:
            self.paths_dropped.emit(paths)
            event.acceptProposedAction()
            return
        super().dropEvent(event)


class EpisodeMappingTable(QTableWidget):
    files_assigned = pyqtSignal(list, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setColumnCount(4)
        self.setHorizontalHeaderLabels(["Folge", "Titel", "Datum", "Zugeordnete Datei"])
        self.verticalHeader().setVisible(False)
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

    def dragEnterEvent(self, event) -> None:
        mime = event.mimeData()
        if mime and (mime.hasFormat(_MAPPING_MIME) or _mime_has_file_payload(mime)):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        mime = event.mimeData()
        if mime and (mime.hasFormat(_MAPPING_MIME) or _mime_has_file_payload(mime)):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        mime = event.mimeData()
        paths: list[str] = []
        if mime.hasFormat(_MAPPING_MIME):
            raw = bytes(mime.data(_MAPPING_MIME)).decode("utf-8", errors="replace")
            paths = [line for line in raw.splitlines() if line.strip()]
        else:
            paths = _extract_paths_from_mime_data(mime)
        if not paths:
            super().dropEvent(event)
            return
        row = self.rowAt(int(event.position().y()))
        if row < 0:
            row = self.currentRow()
        if row < 0:
            row = 0
        self.files_assigned.emit(paths, row)
        event.acceptProposedAction()


class MovieRenamerMetadataBrowserDialog(RenamerBrowserMappingMixin, RenamerBrowserRuntimeMixin, QDialog):
    """Search without local files first, then explicitly map files to metadata."""

    def __init__(self, settings: QSettings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.service = RenamerMetadataBrowserService.from_settings(settings)
        self._workers: set[_BrowserWorker] = set()
        self._request_token = 0
        self._latest_token = 0
        self._busy = False
        self._hits: list[MetadataBrowserHit] = []
        self._current_series_hit: MetadataBrowserHit | None = None
        self._current_movie_hit: MetadataBrowserHit | None = None
        self._episodes: list[MetadataBrowserEpisode] = []
        self._series_mappings: dict[str, ExplicitSeriesFileMapping] = {}
        self._movie_mappings: dict[str, ExplicitMovieFileMapping] = {}
        self._accepted_mappings: list[ExplicitFileMapping] = []

        self.setWindowTitle("Metadaten-Browser / Episoden-Zuordnung")
        self.resize(1180, 780)
        self._build_ui()
        self._connect()
        install_persistent_window_geometry(self, "renamer_metadata_browser")

    @property
    def mappings(self) -> tuple[ExplicitFileMapping, ...]:
        return tuple(self._accepted_mappings)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        info = QLabel(
            "Serie oder Film unabhängig von lokalen Dateinamen suchen. Danach Dateien/Ordner hineinziehen, "
            "explizit zuordnen und die fertigen Vorschläge in den normalen Renamer übernehmen."
        )
        info.setWordWrap(True)
        root.addWidget(info)

        search_row = QHBoxLayout()
        self.kind_combo = QComboBox()
        self.kind_combo.addItem("Serie", "series")
        self.kind_combo.addItem("Film", "movie")
        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText("z. B. Ranma")
        self.search_btn = QPushButton("🔎 Suchen")
        self.load_hit_btn = QPushButton("Treffer laden")
        search_row.addWidget(self.kind_combo)
        search_row.addWidget(self.query_edit, 1)
        search_row.addWidget(self.search_btn)
        search_row.addWidget(self.load_hit_btn)
        root.addLayout(search_row)

        self.results = QTableWidget(0, 4)
        self.results.setHorizontalHeaderLabels(["Titel", "Jahr", "Provider", "ID"])
        self.results.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.results.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.results.verticalHeader().setVisible(False)
        rh = self.results.horizontalHeader()
        rh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        rh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        rh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        rh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.results.setMaximumHeight(220)
        root.addWidget(self.results)

        self.series_controls = QWidget()
        sc = QHBoxLayout(self.series_controls)
        sc.setContentsMargins(0, 0, 0, 0)
        sc.addWidget(QLabel("Staffel:"))
        self.season_combo = QComboBox()
        sc.addWidget(self.season_combo)
        sc.addSpacing(12)
        sc.addWidget(QLabel("Datei umfasst:"))
        self.span_spin = QSpinBox()
        self.span_spin.setRange(1, 4)
        self.span_spin.setValue(1)
        self.span_spin.setSuffix(" Folge(n)")
        sc.addWidget(self.span_spin)
        sc.addSpacing(12)
        sc.addWidget(QLabel("Mehrfachfolge – Titel:"))
        self.title_mode_combo = QComboBox()
        self.title_mode_combo.addItem("Alle Episodentitel", "all")
        self.title_mode_combo.addItem("Nur erster Episodentitel", "first")
        self.title_mode_combo.addItem("Keine Episodentitel", "none")
        sc.addWidget(self.title_mode_combo)
        sc.addStretch(1)
        root.addWidget(self.series_controls)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.episode_table = EpisodeMappingTable()
        splitter.addWidget(self.episode_table)

        source_box = QWidget()
        source_layout = QVBoxLayout(source_box)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.addWidget(QLabel("Lokale Dateien (Dateien oder komplette Ordner hier hineinziehen):"))
        self.source_list = MetadataSourceList()
        source_layout.addWidget(self.source_list, 1)
        source_buttons = QHBoxLayout()
        self.add_source_btn = QPushButton("➕ Dateien/Ordner")
        self.remove_source_btn = QPushButton("➖ Entfernen")
        source_buttons.addWidget(self.add_source_btn)
        source_buttons.addWidget(self.remove_source_btn)
        source_layout.addLayout(source_buttons)
        splitter.addWidget(source_box)
        splitter.setSizes([720, 420])
        root.addWidget(splitter, 1)

        actions = QGridLayout()
        self.assign_btn = QPushButton("Auswahl zu Episode zuordnen")
        self.auto_assign_btn = QPushButton("Ab markierter Episode automatisch zuordnen")
        self.clear_mapping_btn = QPushButton("Zuordnung der Datei(en) lösen")
        self.clear_all_mappings_btn = QPushButton("Alle Zuordnungen löschen")
        actions.addWidget(self.assign_btn, 0, 0)
        actions.addWidget(self.auto_assign_btn, 0, 1)
        actions.addWidget(self.clear_mapping_btn, 1, 0)
        actions.addWidget(self.clear_all_mappings_btn, 1, 1)
        root.addLayout(actions)

        self.status = QLabel("Bereit.")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.import_btn = QPushButton("✅ Zuordnung in Renamer übernehmen")
        self.close_btn = QPushButton("Schließen")
        bottom.addWidget(self.import_btn)
        bottom.addWidget(self.close_btn)
        root.addLayout(bottom)
        self._sync_kind_ui()

    def _connect(self) -> None:
        self.search_btn.clicked.connect(self._search)
        self.query_edit.returnPressed.connect(self._search)
        self.load_hit_btn.clicked.connect(self._load_selected_hit)
        self.results.doubleClicked.connect(lambda _idx: self._load_selected_hit())
        self.kind_combo.currentIndexChanged.connect(self._sync_kind_ui)
        self.season_combo.currentIndexChanged.connect(self._load_current_season)
        self.title_mode_combo.currentIndexChanged.connect(lambda _idx: self._refresh_source_labels())
        self.source_list.paths_dropped.connect(self.add_source_paths)
        self.episode_table.files_assigned.connect(self._drop_assign_to_episode)
        self.add_source_btn.clicked.connect(self._choose_source_paths)
        self.remove_source_btn.clicked.connect(self._remove_selected_sources)
        self.assign_btn.clicked.connect(self._assign_selected)
        self.auto_assign_btn.clicked.connect(self._auto_assign)
        self.clear_mapping_btn.clicked.connect(self._clear_selected_mappings)
        self.clear_all_mappings_btn.clicked.connect(self._clear_all_mappings)
        self.import_btn.clicked.connect(self._accept_mappings)
        self.close_btn.clicked.connect(self.reject)

    def _sync_kind_ui(self) -> None:
        is_series = self._kind() == "series"
        # Provider rows and the loaded season table are one semantic context.
        # Switching kind must invalidate both; existing explicit mappings stay
        # intact, but they cannot silently reactivate an old provider hit.
        self._clear_active_metadata_context()
        self.series_controls.setVisible(is_series)
        self.episode_table.setVisible(is_series)
        self.auto_assign_btn.setVisible(is_series)
        self.assign_btn.setText(
            "Auswahl zu Episode zuordnen" if is_series else "Ausgewählte Datei(en) dem Film zuordnen"
        )
        self.results.setRowCount(0)
        self._hits.clear()
        self.load_hit_btn.setText("Serie laden" if is_series else "Film auswählen")

    def _clear_active_metadata_context(self) -> None:
        self._current_movie_hit = None
        self._current_series_hit = None
        self._episodes = []
        self.episode_table.setRowCount(0)
        self.season_combo.blockSignals(True)
        self.season_combo.clear()
        self.season_combo.blockSignals(False)

    def _kind(self) -> str:
        return str(self.kind_combo.currentData() or "series")

    def _search(self) -> None:
        if self._busy:
            self.status.setText("Bitte die laufende Metadaten-Abfrage abwarten.")
            return
        query = self.query_edit.text().strip()
        if not query:
            QMessageBox.information(self, "Metadaten-Suche", "Bitte einen Suchbegriff eingeben.")
            return
        kind = self._kind()
        # A new query invalidates the previously loaded provider/season context
        # immediately.  Explicit mappings remain stored, but no old episode row
        # can be assigned while the new result set is in flight.
        self._clear_active_metadata_context()
        # Remove stale result rows immediately. A late callback is additionally
        # bound to the kind that started the request.
        self._hits.clear()
        self.results.setRowCount(0)
        self._start_worker(
            lambda: self.service.search(query, kind=kind),
            lambda payload, expected_kind=kind: self._on_search_results(expected_kind, payload),
            busy_text=f"{query!r} wird bei TMDB/TheTVDB gesucht …",
        )

    def _on_search_results(self, expected_kind: str, payload: object) -> None:
        if self._kind() != expected_kind:
            return
        hits = [hit for hit in list(payload or ()) if getattr(hit, "kind", None) == expected_kind]
        self._hits = hits
        self.results.setRowCount(0)
        for hit in hits:
            row = self.results.rowCount()
            self.results.insertRow(row)
            values = (hit.title, str(hit.year or ""), hit.provider_label, str(hit.provider_id))
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self.results.setItem(row, col, item)
        if hits:
            self.results.selectRow(0)
        self.status.setText(f"{len(hits)} Treffer geladen. Treffer markieren und laden/auswählen.")

    def _selected_hit(self) -> MetadataBrowserHit | None:
        row = self.results.currentRow()
        if 0 <= row < len(self._hits):
            return self._hits[row]
        return None

    def _load_selected_hit(self) -> None:
        if self._busy:
            self.status.setText("Bitte die laufende Metadaten-Abfrage abwarten.")
            return
        hit = self._selected_hit()
        if hit is None:
            QMessageBox.information(self, "Metadaten-Browser", "Bitte zuerst einen Treffer markieren.")
            return
        if hit.kind == "movie":
            self._current_movie_hit = hit
            self.status.setText(f"Aktiver Film: {hit.display_title} · {hit.provider_label} · ID {hit.provider_id}")
            return
        mapped_hits = {
            (mapping.hit.provider, mapping.hit.provider_id)
            for mapping in self._series_mappings.values()
        }
        selected_hit_key = (hit.provider, hit.provider_id)
        if mapped_hits and mapped_hits != {selected_hit_key}:
            reply = QMessageBox.question(
                self,
                "Serie wechseln",
                "Es existieren bereits Episodenzuordnungen. Beim Wechsel der Serie werden diese gelöscht. Fortfahren?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            self._series_mappings.clear()
            self._refresh_source_labels()
        self._current_movie_hit = None
        self._current_series_hit = hit
        # The old episode table must never remain assignable while the new
        # series/season metadata is still in flight.
        self._episodes = []
        self.episode_table.setRowCount(0)
        self.season_combo.blockSignals(True)
        self.season_combo.clear()
        self.season_combo.blockSignals(False)
        self._start_worker(
            lambda: self.service.series_seasons(hit),
            lambda payload, selected=hit: self._on_seasons_loaded(selected, payload),
            busy_text=f"Staffeln für {hit.display_title} werden geladen …",
        )

    def _on_seasons_loaded(self, hit: MetadataBrowserHit, payload: object) -> None:
        if self._current_series_hit != hit:
            return
        seasons = list(payload or ())
        self.season_combo.blockSignals(True)
        self.season_combo.clear()
        for season in seasons:
            label = "Specials (S00)" if int(season) == 0 else f"Staffel {int(season)}"
            self.season_combo.addItem(label, int(season))
        target_index = self.season_combo.findData(1)
        self.season_combo.setCurrentIndex(target_index if target_index >= 0 else (0 if seasons else -1))
        self.season_combo.blockSignals(False)
        if seasons:
            self._load_current_season()
        else:
            self.episode_table.setRowCount(0)
            self.status.setText(f"{hit.display_title}: keine Staffeln gefunden.")

    def _load_current_season(self) -> None:
        if self._current_series_hit is None:
            return
        season = self.season_combo.currentData()
        if season is None:
            return
        hit = self._current_series_hit
        season = int(season)
        # A season switch is asynchronous. Clear the previous rows before the
        # request starts so a fast click/drop cannot map against stale episodes.
        self._episodes = []
        self.episode_table.setRowCount(0)
        self._start_worker(
            lambda: self.service.series_episodes(hit, season),
            lambda payload, selected=hit, s=season: self._on_episodes_loaded(selected, s, payload),
            busy_text=f"{hit.display_title} · Staffel {season}: Episoden werden geladen …",
        )

    def _on_episodes_loaded(self, hit: MetadataBrowserHit, season: int, payload: object) -> None:
        current_season = self.season_combo.currentData()
        if (
            self._current_series_hit != hit
            or current_season is None
            or int(current_season) != season
        ):
            return
        self._episodes = list(payload or ())
        self.episode_table.setRowCount(0)
        for episode in self._episodes:
            row = self.episode_table.rowCount()
            self.episode_table.insertRow(row)
            values = (episode.code, episode.title, episode.air_date, "")
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self.episode_table.setItem(row, col, item)
        if self._episodes:
            self.episode_table.selectRow(0)
        self._refresh_episode_mapping_column()
        self.status.setText(f"{hit.display_title} · Staffel {season}: {len(self._episodes)} Episoden geladen.")

    def _choose_source_paths(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Videodateien hinzufügen")
        if paths:
            self.add_source_paths(paths)
            return
        folder = QFileDialog.getExistingDirectory(self, "Oder Ordner auswählen")
        if folder:
            self.add_source_paths([folder])

    def add_source_paths(self, paths: list[str]) -> list[str]:
        expanded: list[str] = []
        ignored = 0
        for raw in paths:
            path = Path(raw)
            if path.is_dir():
                files, folder_ignored = iter_video_files_in_folder(str(path))
                expanded.extend(files)
                ignored += int(folder_ignored)
            elif is_video_file(path):
                expanded.append(str(path))
            else:
                ignored += 1
        expanded = sorted(dedupe_paths(expanded), key=natural_path_key)
        existing = {
            path_compare_key(str(self.source_list.item(i).data(Qt.ItemDataRole.UserRole) or ""))
            for i in range(self.source_list.count())
        }
        added: list[str] = []
        for path in expanded:
            if path_compare_key(path) in existing:
                continue
            item = QListWidgetItem(Path(path).name)
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path)
            self.source_list.addItem(item)
            existing.add(path_compare_key(path))
            added.append(path)
        self._refresh_source_labels()
        message = f"{len(added)} Videodatei(en) hinzugefügt."
        if ignored:
            message += f" {ignored} Nicht-Videoeinträge ignoriert."
        self.status.setText(message)
        return added

    def _new_browser_worker(self, token, fn):
        return _BrowserWorker(token, fn, QApplication.instance())


__all__ = ["MovieRenamerMetadataBrowserDialog"]
