# -*- coding: utf-8 -*-
"""Qt view primitives for the movie/series renamer.

This module owns widget construction and drag/drop presentation only.  It must
not perform metadata lookup, filesystem renames, or proposal scoring.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.settings import APP_VERSION
from .file_drop_widgets import FileDropTable


class RenameTable(FileDropTable):
    pass


class WideCandidateComboBox(QComboBox):
    """Candidate combo whose popup expands without widening the table column."""

    _POPUP_HORIZONTAL_PADDING = 56

    def showPopup(self) -> None:
        try:
            view = self.view()
            metrics = view.fontMetrics()
            content_width = max(
                (metrics.horizontalAdvance(self.itemText(index)) for index in range(self.count())),
                default=self.width(),
            )
            popup_width = max(self.width(), content_width + self._POPUP_HORIZONTAL_PADDING)

            screen = self.screen()
            if screen is not None:
                available_width = max(self.width(), screen.availableGeometry().width() - 80)
                popup_width = min(popup_width, available_width)

            view.setTextElideMode(Qt.TextElideMode.ElideNone)
            view.setMinimumWidth(popup_width)
        except Exception:
            # Presentation errors must never make the selector unusable.
            pass
        super().showPopup()


class MovieRenamerView:
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
        "Sicherheit",
        "Neuer Dateiname",
        "Hinweise",
    )

    def __init__(self, owner: QWidget, columns) -> None:
        self.owner = owner
        self.columns = columns
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self.owner)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        title = QLabel(f"🎞 Renamer – Dragon Tools V{APP_VERSION}")
        title.setStyleSheet("font-weight:bold;font-size:15px;")
        root.addWidget(title)

        hint = QLabel(
            "Dateien hinzufügen, Metadaten-Vorschläge laden, gewünschte Zeilen akzeptieren "
            "und erst danach die Umbenennung ausführen."
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        toolbar = QHBoxLayout()
        self.add_files_btn = QPushButton("➕ Dateien")
        self.add_folder_btn = QPushButton("📁 Ordner")
        self.resolve_btn = QPushButton("🔎 Vorschläge suchen")
        self.manual_series_search_btn = QPushButton("🔍 Eigene Seriensuche")
        self.accept_selected_btn = QPushButton("✅ Auswahl akzeptieren")
        self.accept_safe_btn = QPushButton("✅ Sichere akzeptieren")
        self.reject_selected_btn = QPushButton("🚫 Auswahl ablehnen")
        self.rename_btn = QPushButton("🏷 Umbenennen ausführen")
        self.remove_btn = QPushButton("➖ Entfernen")
        self.clear_btn = QPushButton("🗑 Alle")
        for button in self.action_buttons:
            toolbar.addWidget(button)
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
        for column in (self.columns.ACCEPT, self.columns.STATUS, self.columns.TYPE):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.columns.SOURCE, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self.columns.QUERY, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.columns.SERIES, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.columns.YEAR, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.columns.MATCH, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self.columns.SCORE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.columns.TARGET, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self.columns.HINTS, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)

        self.status_lbl = QLabel("Bereit. Dateien oder Ordner können auch auf die Tabelle gezogen werden.")
        self.status_lbl.setStyleSheet("color:#555;")
        root.addWidget(self.status_lbl)

    @property
    def action_buttons(self) -> tuple[QPushButton, ...]:
        return (
            self.add_files_btn,
            self.add_folder_btn,
            self.resolve_btn,
            self.manual_series_search_btn,
            self.accept_selected_btn,
            self.accept_safe_btn,
            self.reject_selected_btn,
            self.rename_btn,
            self.remove_btn,
            self.clear_btn,
        )

    @property
    def lockable_buttons(self) -> tuple[QPushButton, ...]:
        return (
            self.resolve_btn,
            self.manual_series_search_btn,
            self.accept_selected_btn,
            self.accept_safe_btn,
            self.reject_selected_btn,
            self.rename_btn,
            self.remove_btn,
            self.clear_btn,
        )

    def set_busy(self, busy: bool) -> None:
        # Adding files remains possible while metadata is resolved. Removing or
        # reordering rows is blocked so worker row indices remain stable.
        self.add_files_btn.setEnabled(True)
        self.add_folder_btn.setEnabled(True)
        for button in self.lockable_buttons:
            button.setEnabled(not busy)
