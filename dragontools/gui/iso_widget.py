from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..core.formatting import format_binary_size
from ..worker.iso_thread import ISOThread
from ..worker.iso_selection import choose_auto_titles


def _safe_display_name(path: str) -> str:
    try:
        return Path(path).name
    except Exception:
        return path


def _fmt_duration(seconds: int) -> str:
    total = max(0, int(seconds or 0))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _fmt_size(value: int) -> str:
    return format_binary_size(value, decimals=1)


class ISOWidget(QWidget):
    """DVD-/Blu-ray-ISO-Handling über MakeMKV CLI mit optionalem FFmpeg-Fallback."""

    # Emittiert nach Abschluss wenn 'handoff_cb' aktiv – enthält alle extrahierten MKV-Pfade
    handoff_requested = pyqtSignal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._extracted_files: list[str] = []
        self.input_list: QListWidget | None = None
        self.title_list: QListWidget | None = None
        self.output_edit: QLineEdit | None = None
        self.auto_main_title_cb: QCheckBox | None = None
        self.auto_series_disc_cb: QCheckBox | None = None
        self.ffmpeg_fallback_cb: QCheckBox | None = None
        self.handoff_cb: QCheckBox | None = None
        self.progress_bar: QProgressBar | None = None
        self.log_edit: QTextEdit | None = None
        self._btn_add_iso: QPushButton | None = None
        self._btn_add_folder: QPushButton | None = None
        self._btn_remove: QPushButton | None = None
        self._btn_clear: QPushButton | None = None
        self._btn_analyze: QPushButton | None = None
        self._btn_browse: QPushButton | None = None
        self._btn_start: QPushButton | None = None
        self._btn_abort: QPushButton | None = None
        self._worker: ISOThread | None = None
        self._scan_worker: ISOThread | None = None
        self._analyzed_input_path: str | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        root.addWidget(QLabel("ISO-Handling / Disc-Import"))
        structure_hint = QLabel(
            "Unterstützt werden ISO/IMG-Dateien, Disc-Root-Ordner und direkt ausgewählte BDMV-/VIDEO_TS-Ordner. "
            "Blu-ray-Struktur: Disc-Ordner\\BDMV\\index.bdmv, PLAYLIST\\*.mpls, STREAM\\*.m2ts, CLIPINF\\*.clpi; "
            "CERTIFICATE ist optional. MakeMKV ist der bevorzugte Weg, FFmpeg dient nur als Fallback."
        )
        structure_hint.setWordWrap(True)
        structure_hint.setStyleSheet("color: #444;")
        root.addWidget(structure_hint)

        self.input_list = QListWidget()
        self.input_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        root.addWidget(self.input_list)

        input_btns = QHBoxLayout()
        self._btn_add_iso = QPushButton("➕ ISO-Dateien")
        self._btn_add_iso.clicked.connect(self._add_iso_files)
        self._btn_add_folder = QPushButton("📁 Disc-Ordner")
        self._btn_add_folder.clicked.connect(self._add_disc_folder)
        self._btn_remove = QPushButton("➖ Entfernen")
        self._btn_remove.clicked.connect(self._remove_selected)
        self._btn_clear = QPushButton("🗑️ Alle")
        self._btn_clear.clicked.connect(self._clear_inputs)
        self._btn_analyze = QPushButton("Titel analysieren")
        self._btn_analyze.clicked.connect(self._analyze)
        input_btns.addWidget(self._btn_add_iso)
        input_btns.addWidget(self._btn_add_folder)
        input_btns.addWidget(self._btn_remove)
        input_btns.addWidget(self._btn_clear)
        input_btns.addWidget(self._btn_analyze)
        root.addLayout(input_btns)

        root.addWidget(QLabel("Titel-Auswahl:"))
        self.title_list = QListWidget()
        self.title_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        root.addWidget(self.title_list)

        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Zielpfad:"))
        self.output_edit = QLineEdit()
        out_row.addWidget(self.output_edit)
        self._btn_browse = QPushButton("Durchsuchen")
        self._btn_browse.clicked.connect(self._browse_output)
        out_row.addWidget(self._btn_browse)
        root.addLayout(out_row)

        self.auto_main_title_cb = QCheckBox("Haupttitel automatisch vorschlagen")
        self.auto_main_title_cb.setChecked(True)
        root.addWidget(self.auto_main_title_cb)

        self.auto_series_disc_cb = QCheckBox("Serien-Disc automatisch erkennen")
        self.auto_series_disc_cb.setChecked(True)
        self.auto_series_disc_cb.setToolTip(
            "Erkennt mehrere ähnlich lange Titel als einzelne Episoden und bevorzugt sie "
            "gegenüber einem langen 'Alle abspielen'-Sammeltitel. Abschalten verwendet "
            "wieder ausschließlich den längsten Haupttitel."
        )
        root.addWidget(self.auto_series_disc_cb)

        self.ffmpeg_fallback_cb = QCheckBox("FFmpeg-Fallback verwenden, wenn MakeMKV scheitert")
        self.ffmpeg_fallback_cb.setChecked(True)
        self.ffmpeg_fallback_cb.setToolTip(
            "Versucht bei fehlender/ungültiger MakeMKV-Freischaltung oder MakeMKV-Fehlern "
            "einen reinen FFmpeg-Remux. Funktioniert nur bei unverschlüsselten, direkt lesbaren "
            "ISO-/Disc-Strukturen und ist weniger zuverlässig als MakeMKV."
        )
        root.addWidget(self.ffmpeg_fallback_cb)

        self.handoff_cb = QCheckBox("Nach Extraktion an Konverter übergeben")
        root.addWidget(self.handoff_cb)

        btn_row = QHBoxLayout()
        self._btn_start = QPushButton("Extraktion starten")
        self._btn_start.clicked.connect(self._start)
        self._btn_abort = QPushButton("Abbrechen")
        self._btn_abort.clicked.connect(self._abort)
        self._btn_abort.setEnabled(False)
        btn_row.addWidget(self._btn_start)
        btn_row.addWidget(self._btn_abort)
        root.addLayout(btn_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        root.addWidget(self.progress_bar)

        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        root.addWidget(self.log_edit)

    def _append_log(self, text: str) -> None:
        if self.log_edit is not None:
            self.log_edit.append(text)

    def _add_paths(self, paths: list[str]) -> None:
        if self.input_list is None:
            return
        existing = {
            str(Path(self.input_list.item(i).text()).resolve())
            for i in range(self.input_list.count())
        }
        added = 0
        for raw in paths:
            if not raw:
                continue
            path = str(Path(raw).resolve())
            if path in existing:
                continue
            self.input_list.addItem(path)
            existing.add(path)
            added += 1
        if added:
            self._append_log(f"ℹ️ {added} Eingabe(n) hinzugefügt.")

    def _add_iso_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "ISO-Dateien auswählen",
            "",
            "ISO-Dateien (*.iso);;Alle Dateien (*)",
        )
        self._add_paths(paths)

    def _add_disc_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Disc-Ordner auswählen", "")
        if folder:
            self._add_paths([folder])

    def _remove_selected(self) -> None:
        if self.input_list is None:
            return
        rows = sorted({idx.row() for idx in self.input_list.selectedIndexes()}, reverse=True)
        if not rows:
            return
        removed_paths = []
        for row in rows:
            item = self.input_list.takeItem(row)
            if item is not None:
                removed_paths.append(item.text())
        if self._analyzed_input_path and self._analyzed_input_path in removed_paths:
            self._analyzed_input_path = None
            if self.title_list is not None:
                self.title_list.clear()
        self._append_log(f"ℹ️ {len(removed_paths)} Eingabe(n) entfernt.")

    def _clear_inputs(self) -> None:
        if self.input_list is not None:
            self.input_list.clear()
        if self.title_list is not None:
            self.title_list.clear()
        self._analyzed_input_path = None
        self._append_log("ℹ️ Eingabeliste geleert.")

    def _browse_output(self) -> None:
        if self.output_edit is None:
            return
        folder = QFileDialog.getExistingDirectory(self, "Zielordner wählen", self.output_edit.text())
        if folder:
            self.output_edit.setText(folder)

    def _current_input_path(self) -> str | None:
        if self.input_list is None or self.input_list.count() == 0:
            return None
        current = self.input_list.currentItem()
        if current is not None:
            return current.text()
        if self.input_list.selectedItems():
            return self.input_list.selectedItems()[0].text()
        return self.input_list.item(0).text()

    def _collect_selected_titles(self) -> dict[str, list[int]]:
        if self.title_list is None or not self._analyzed_input_path:
            return {}
        title_ids: list[int] = []
        for item in self.title_list.selectedItems():
            tid = item.data(Qt.ItemDataRole.UserRole)
            path = item.data(Qt.ItemDataRole.UserRole + 1)
            if path == self._analyzed_input_path and isinstance(tid, int):
                title_ids.append(tid)
        return {self._analyzed_input_path: title_ids} if title_ids else {}

    def _analyze(self) -> None:
        if self._worker is not None or self._scan_worker is not None:
            return
        path = self._current_input_path()
        if not path:
            self._append_log("⚠️ Keine ISO-/Disc-Eingabe zum Analysieren ausgewählt.")
            return
        if self.title_list is None:
            self._append_log("❌ ISO-Titelliste ist nicht initialisiert.")
            return
        self.title_list.clear()
        self._analyzed_input_path = path

        self._scan_worker = ISOThread(
            inputs=[path],
            output_dir=self.output_edit.text().strip() if self.output_edit is not None else None,
            selected_titles={},
            auto_main_title=self.auto_main_title_cb.isChecked() if self.auto_main_title_cb is not None else True,
            auto_series_disc=self.auto_series_disc_cb.isChecked() if self.auto_series_disc_cb is not None else True,
            handoff_to_converter=self.handoff_cb.isChecked() if self.handoff_cb is not None else False,
            ffmpeg_fallback=self.ffmpeg_fallback_cb.isChecked() if self.ffmpeg_fallback_cb is not None else True,
            scan_only=True,
        )
        self._scan_worker.log_line.connect(self._append_log)
        self._scan_worker.progress.connect(self._on_progress)
        self._scan_worker.file_progress.connect(self._on_scan_file_progress)
        self._scan_worker.file_result.connect(self._on_scan_file_result)
        self._scan_worker.finished.connect(self._on_scan_finished)

        self._append_log("")
        self._append_log(f"▶ Analysiere {_safe_display_name(path)} …")
        self._set_running(True)
        self._scan_worker.start()

    def _set_running(self, running: bool) -> None:
        for widget in (
            self.input_list,
            self.title_list,
            self.output_edit,
            self.auto_main_title_cb,
            self.auto_series_disc_cb,
            self.ffmpeg_fallback_cb,
            self.handoff_cb,
            self._btn_add_iso,
            self._btn_add_folder,
            self._btn_remove,
            self._btn_clear,
            self._btn_analyze,
            self._btn_browse,
            self._btn_start,
        ):
            if widget is not None:
                widget.setEnabled(not running)
        if self._btn_abort is not None:
            self._btn_abort.setEnabled(running)

    def _start(self) -> None:
        if self._worker is not None:
            return
        if self.input_list is None or self.input_list.count() == 0:
            self._append_log("⚠️ Keine Eingaben vorhanden.")
            return
        output_dir = self.output_edit.text().strip() if self.output_edit is not None else ""
        if not output_dir:
            self._append_log("⚠️ Kein Zielpfad gewählt.")
            return

        files = [self.input_list.item(i).text() for i in range(self.input_list.count())]
        if len(files) > 1 and self._analyzed_input_path:
            self._append_log(
                "ℹ️ Explizite Titelauswahl gilt aktuell nur für die zuletzt analysierte Quelle. "
                "Alle anderen Eingaben verwenden den Auto-Vorschlag des Workers."
            )
        selected_titles = self._collect_selected_titles()
        self._worker = ISOThread(
            inputs=files,
            output_dir=output_dir,
            selected_titles=selected_titles,
            auto_main_title=self.auto_main_title_cb.isChecked() if self.auto_main_title_cb is not None else True,
            auto_series_disc=self.auto_series_disc_cb.isChecked() if self.auto_series_disc_cb is not None else True,
            handoff_to_converter=self.handoff_cb.isChecked() if self.handoff_cb is not None else False,
            ffmpeg_fallback=self.ffmpeg_fallback_cb.isChecked() if self.ffmpeg_fallback_cb is not None else True,
        )
        self._worker.log_line.connect(self._append_log)
        self._worker.progress.connect(self._on_progress)
        self._worker.file_progress.connect(self._on_file_progress)
        self._worker.file_result.connect(self._on_file_result)
        self._worker.files_extracted.connect(self._on_files_extracted)
        self._worker.finished.connect(self._on_finished)

        if self.progress_bar is not None:
            self.progress_bar.setValue(0)
        self._append_log("")
        self._append_log(f"▶ Starte ISO-Extraktion für {len(files)} Eingabe(n) …")
        self._set_running(True)
        self._worker.start()

    def iter_shutdown_workers(self) -> tuple:
        return tuple(worker for worker in (self._worker, self._scan_worker) if worker is not None)

    def _abort(self) -> None:
        if self._worker is not None:
            self._worker.request_abort()
            self._append_log("⚠️ Abbruch angefordert ...")
        elif self._scan_worker is not None:
            self._scan_worker.request_abort()
            self._append_log("⚠️ Analyse-Abbruch angefordert ...")

    def _on_progress(self, pct: int) -> None:
        if self.progress_bar is not None:
            self.progress_bar.setValue(pct)

    def _on_file_progress(self, path: str, pct: int, obj) -> None:
        if self.progress_bar is not None:
            self.progress_bar.setValue(pct)
        if isinstance(obj, list) and obj:
            if isinstance(obj[0], dict):
                self._append_log(f"ℹ️ {_safe_display_name(path)}: {len(obj)} Titel gescannt.")
            elif isinstance(obj[0], int):
                self._append_log(f"ℹ️ {_safe_display_name(path)}: Titel {', '.join(map(str, obj))} ausgewählt.")

    def _on_file_result(self, path: str, success: bool, message: str) -> None:
        icon = "✅" if success else "❌"
        self._append_log(f"{icon} {_safe_display_name(path)} → {message}")

    def _on_scan_file_progress(self, path: str, pct: int, obj) -> None:
        if self.progress_bar is not None:
            self.progress_bar.setValue(pct)
        if not (isinstance(obj, list) and obj and isinstance(obj[0], dict)):
            return
        if self.title_list is None:
            self._append_log("❌ ISO-Titelliste ist nicht initialisiert; Scan-Ergebnis wird verworfen.")
            return
        self.title_list.clear()
        suggested: set[int] = set()
        series_disc = False
        if self._scan_worker is not None and self.auto_main_title_cb is not None and self.auto_main_title_cb.isChecked():
            suggested_ids, series_disc = choose_auto_titles(
                obj,
                detect_series_disc=(
                    self.auto_series_disc_cb.isChecked()
                    if self.auto_series_disc_cb is not None
                    else True
                ),
            )
            suggested = set(suggested_ids)
        for title in obj:
            tid = int(title.get("id") or 0)
            duration = int(title.get("duration") or 0)
            size = int(title.get("size") or 0)
            name = str(title.get("name") or f"Title {tid}")
            prefix = "★ " if tid in suggested else ""
            text = f"{prefix}Titel {tid}: {name} | Dauer {_fmt_duration(duration)} | Größe {_fmt_size(size)}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, tid)
            item.setData(Qt.ItemDataRole.UserRole + 1, path)
            self.title_list.addItem(item)
        if suggested:
            if series_disc:
                self._append_log(
                    f"ℹ️ Serien-Disc erkannt; Episoden-Titel sichtbar markiert: "
                    f"{', '.join(map(str, sorted(suggested)))}"
                )
            else:
                self._append_log(f"ℹ️ Haupttitel-Vorschlag sichtbar markiert: Titel {next(iter(suggested))}")

    def _on_scan_file_result(self, path: str, success: bool, message: str) -> None:
        icon = "✅" if success else "❌"
        self._append_log(f"{icon} {_safe_display_name(path)} → {message}")

    def _on_scan_finished(self) -> None:
        self._set_running(False)
        self._scan_worker = None
        self._append_log("")
        self._append_log("🏁 Analyse abgeschlossen.")

    def _on_files_extracted(self, paths: list[str]) -> None:
        """Vom Worker empfangene MKV-Pfade zwischenspeichern."""
        self._extracted_files = list(paths)

    def _on_finished(self) -> None:
        self._set_running(False)
        self._worker = None
        self._append_log("")
        self._append_log("🏁 ISO-Verarbeitung abgeschlossen.")

        # Handoff an Konverter – nur wenn Checkbox aktiv und Dateien vorhanden
        if (
            self.handoff_cb is not None
            and self.handoff_cb.isChecked()
            and self._extracted_files
        ):
            n = len(self._extracted_files)
            self._append_log(f"➡️ Übergebe {n} Datei(en) an den Konverter …")
            self.handoff_requested.emit(list(self._extracted_files))
        self._extracted_files = []
