# -*- coding: utf-8 -*-
"""Qt view primitives for the movie/series renamer.

This module owns widget construction and drag/drop presentation only.  It must
not perform metadata lookup, filesystem renames, or proposal scoring.
"""
from __future__ import annotations
from PyQt6.QtCore import QSettings, QSize, QTimer, Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QGridLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.version import APP_VERSION
from .file_drop_widgets import FileDropTable
from .movie_renamer_view_state import MovieRenamerViewStateMixin




class RenamerStatusLabel(QLabel):
    """Wrapped status text that never contributes horizontal minimum width."""

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        return QSize(0, hint.height())

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        return QSize(min(hint.width(), 640), hint.height())


class RenameTable(FileDropTable):
    """Scrollable renamer table that never dictates the window minimum width.

    Removing a row can leave transient editor/cell-widget geometry cached until
    Qt processes deferred deletes.  The table therefore explicitly invalidates
    the geometry chain after row removals.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.model().rowsRemoved.connect(self._schedule_geometry_refresh)
        self.model().modelReset.connect(self._schedule_geometry_refresh)

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        return QSize(0, hint.height())

    def _schedule_geometry_refresh(self, *_args) -> None:
        QTimer.singleShot(0, self._refresh_geometry_chain)

    def _refresh_geometry_chain(self) -> None:
        widget: QWidget | None = self
        while widget is not None:
            widget.updateGeometry()
            layout = widget.layout()
            if layout is not None:
                layout.invalidate()
            widget = widget.parentWidget()


class MovieRenamerView(MovieRenamerViewStateMixin):
    """Builds and owns the visible controls of ``MovieRenamerWidget``."""

    COLUMN_HEADERS = (
        "OK",
        "Status",
        "Typ",
        "Quelldatei",
        "Suchname",
        "Serie",
        "Jahr",
        "Vorschlag",
        "Provider",
        "Sicherheit",
        "Neuer Dateiname",
        "Hinweise",
    )

    _HEADER_STATE_KEY = "renamer/table_header_state_v2"

    def __init__(self, owner: QWidget, columns, settings: QSettings | None = None) -> None:
        self.owner = owner
        self.columns = columns
        self.settings = settings
        self._column_actions = []
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self.owner)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        title_row = QHBoxLayout()
        title = QLabel(f"🎞 Renamer – Dragon Tools V{APP_VERSION}")
        title.setStyleSheet("font-weight:bold;font-size:15px;")
        title_row.addWidget(title, 1)

        self.columns_btn = QPushButton("⚙ Spalten")
        self.columns_btn.setToolTip("Spalten ein-/ausblenden und Standardansicht wiederherstellen")
        title_row.addWidget(self.columns_btn)
        root.addLayout(title_row)

        hint = QLabel(
            "Dateien hinzufügen, Metadaten-Vorschläge laden, gewünschte Zeilen akzeptieren "
            "und erst danach die Umbenennung ausführen."
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        # Die frühere einzelne QHBoxLayout-Zeile enthielt 13 Buttons. Deren
        # aufsummierte minimumSizeHint-Breiten wurden bis zum QMainWindow
        # propagiert. Nachdem der Renamer einmal geladen war, ließ sich das
        # gesamte Hauptfenster dadurch kaum noch verkleinern - selbst auf
        # einem anderen Tab. Mehrere logische Reihen halten die Bedienung
        # vollständig sichtbar, ohne eine riesige Mindestbreite zu erzwingen.
        toolbar = QGridLayout()
        toolbar.setHorizontalSpacing(6)
        toolbar.setVerticalSpacing(6)
        self.add_files_btn = QPushButton("➕ Dateien")
        self.add_folder_btn = QPushButton("📁 Ordner")
        self.resolve_btn = QPushButton("🔎 Vorschläge suchen")
        self.manual_series_search_btn = QPushButton("📺 Als Serie suchen")
        self.manual_movie_search_btn = QPushButton("🎬 Als Film suchen")
        self.show_all_candidates_btn = QPushButton("🔎 Alle Treffer")
        self.edit_search_btn = QPushButton("✏️ Suchbegriff")
        self.edit_season_btn = QPushButton("🗓 Staffel ändern")
        self.accept_selected_btn = QPushButton("✅ Auswahl akzeptieren")
        self.accept_safe_btn = QPushButton("✅ Sichere akzeptieren")
        self.reject_selected_btn = QPushButton("🚫 Auswahl ablehnen")
        self.rename_btn = QPushButton("🏷 Umbenennen ausführen")
        self.remove_btn = QPushButton("➖ Entfernen")
        self.clear_btn = QPushButton("🗑 Alle")

        toolbar_rows = (
            (self.add_files_btn, self.add_folder_btn, self.resolve_btn,
             self.manual_series_search_btn, self.manual_movie_search_btn),
            (self.show_all_candidates_btn, self.edit_search_btn, self.edit_season_btn,
             self.accept_selected_btn, self.accept_safe_btn, self.reject_selected_btn),
            (self.rename_btn, self.remove_btn, self.clear_btn),
        )
        for row_index, buttons in enumerate(toolbar_rows):
            for column_index, button in enumerate(buttons):
                toolbar.addWidget(button, row_index, column_index)
        toolbar.setColumnStretch(5, 1)
        root.addLayout(toolbar)

        self.table = RenameTable()
        self.table.setColumnCount(len(self.COLUMN_HEADERS))
        self.table.setHorizontalHeaderLabels(list(self.COLUMN_HEADERS))
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setSortingEnabled(False)
        self.table.verticalHeader().setVisible(False)

        header = self.table.horizontalHeader()
        header.setSectionsMovable(True)
        header.setMinimumSectionSize(36)
        # A stale pre-fix header state must never restore a multi-thousand-pixel
        # section and thereby force the QMainWindow minimum width.
        header.setMaximumSectionSize(1200)
        header.setStretchLastSection(False)
        # Alle Spalten sind bewusst interaktiv. So kann keine
        # ResizeToContents-/Stretch-Kombination die Fensterbreite diktieren und
        # der Nutzer kann jede sichtbare Spalte frei größer oder kleiner ziehen.
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)

        self._default_column_widths = {
            self.columns.ACCEPT: 48,
            self.columns.STATUS: 88,
            self.columns.TYPE: 72,
            self.columns.SOURCE: 330,
            self.columns.QUERY: 150,
            self.columns.SERIES: 210,
            self.columns.YEAR: 70,
            self.columns.MATCH: 340,
            self.columns.PROVIDER: 115,
            self.columns.SCORE: 95,
            self.columns.TARGET: 340,
            self.columns.HINTS: 260,
        }
        for column, width in self._default_column_widths.items():
            self.table.setColumnWidth(column, width)

        self._setup_column_menu()
        self._restore_header_state()
        header.sectionResized.connect(self._save_header_state)
        header.sectionMoved.connect(self._save_header_state)
        root.addWidget(self.table, 1)

        self.status_lbl = RenamerStatusLabel("Bereit. Dateien oder Ordner können auch auf die Tabelle gezogen werden.")
        self.status_lbl.setStyleSheet("color:#555;")
        # Jellyfin runs asynchronously after a rename and may return a long
        # fallback/error message containing full local/server paths.  A plain
        # QLabel uses the unwrapped text width as a layout hint, which can force
        # the entire QMainWindow to several thousand pixels until the next short
        # status message replaces it.  Keep status text informative without ever
        # letting it dictate the window minimum width.
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setMinimumWidth(0)
        self.status_lbl.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        root.addWidget(self.status_lbl)

