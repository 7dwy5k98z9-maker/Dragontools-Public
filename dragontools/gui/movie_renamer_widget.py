# -*- coding: utf-8 -*-
"""Movie/series renamer widget.

The widget is intentionally a thin Qt orchestrator.  View construction,
table/proposal state, metadata lifecycle, and filesystem rename actions live in
focused collaborators so this class does not grow back into a GUI God Object.
"""
from __future__ import annotations

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QWidget

from ..core.settings import APP_NAME, APP_ORG
from .movie_renamer_actions import MovieRenamerActionController
from .movie_renamer_resolver import MovieRenamerResolveCoordinator
from .movie_renamer_table_controller import (
    MovieRenamerTableController,
    RenamerColumns,
)
from .movie_renamer_view import MovieRenamerView


class MovieRenamerWidget(QWidget):
    COL_ACCEPT = RenamerColumns.ACCEPT
    COL_STATUS = RenamerColumns.STATUS
    COL_TYPE = RenamerColumns.TYPE
    COL_SOURCE = RenamerColumns.SOURCE
    COL_QUERY = RenamerColumns.QUERY
    COL_SERIES = RenamerColumns.SERIES
    COL_YEAR = RenamerColumns.YEAR
    COL_MATCH = RenamerColumns.MATCH
    COL_SCORE = RenamerColumns.SCORE
    COL_TARGET = RenamerColumns.TARGET
    COL_HINTS = RenamerColumns.HINTS

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = QSettings(APP_ORG, APP_NAME)
        self._view = MovieRenamerView(self, RenamerColumns)
        self._bind_view_attributes()
        self._table_controller = MovieRenamerTableController(self.table)
        self._resolver = MovieRenamerResolveCoordinator(
            self,
            self.settings,
            self._table_controller,
            self._view,
        )
        self._actions = MovieRenamerActionController(
            self,
            self._view,
            self._table_controller,
            self._resolver,
        )
        self._connect_actions()

    def _bind_view_attributes(self) -> None:
        # Keep the public/widget attribute surface stable for callers and tests.
        for name in (
            "add_files_btn",
            "add_folder_btn",
            "resolve_btn",
            "manual_series_search_btn",
            "accept_selected_btn",
            "accept_safe_btn",
            "reject_selected_btn",
            "rename_btn",
            "remove_btn",
            "clear_btn",
            "table",
            "status_lbl",
        ):
            setattr(self, name, getattr(self._view, name))

    def _connect_actions(self) -> None:
        self.add_files_btn.clicked.connect(self._actions.choose_files)
        self.add_folder_btn.clicked.connect(self._actions.choose_folder)
        self.resolve_btn.clicked.connect(self.resolve_proposals)
        self.manual_series_search_btn.clicked.connect(self._actions.manual_series_search)
        self.accept_selected_btn.clicked.connect(self.accept_selected)
        self.accept_safe_btn.clicked.connect(self.accept_safe)
        self.reject_selected_btn.clicked.connect(self.reject_selected)
        self.rename_btn.clicked.connect(self.execute_rename)
        self.remove_btn.clicked.connect(self.remove_selected)
        self.clear_btn.clicked.connect(self.clear)
        self.table.paths_dropped.connect(self.add_paths)

    # ---- public user actions -------------------------------------------------
    def add_paths(self, paths: list[str]) -> None:
        self._actions.add_paths(paths)

    def resolve_proposals(self) -> None:
        self._resolver.resolve_all()

    def accept_selected(self) -> None:
        self._actions.accept_selected()

    def accept_safe(self) -> None:
        self._actions.accept_safe()

    def reject_selected(self) -> None:
        self._actions.reject_selected()

    def execute_rename(self) -> None:
        self._actions.execute_rename()

    def remove_selected(self) -> None:
        self._actions.remove_selected()

    def clear(self) -> None:
        self._actions.clear()

    # ---- lifecycle -----------------------------------------------------------
    def iter_shutdown_workers(self) -> tuple:
        thread = self._resolver.thread
        return (thread,) if thread is not None else ()

    def closeEvent(self, event) -> None:
        self._resolver.shutdown()
        super().closeEvent(event)
