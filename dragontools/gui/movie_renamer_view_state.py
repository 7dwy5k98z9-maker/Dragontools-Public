# -*- coding: utf-8 -*-
"""Column-state and button-state helpers for the Renamer view."""
from __future__ import annotations

from PyQt6.QtWidgets import QMenu


class MovieRenamerViewStateMixin:
    """Persisted table presentation and busy-state behavior."""

    def _setup_column_menu(self) -> None:
        menu = QMenu(self.columns_btn)
        self._column_actions.clear()
        for column, label in enumerate(self.COLUMN_HEADERS):
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(True)
            action.toggled.connect(
                lambda visible, col=column: self._set_column_visible(col, visible)
            )
            self._column_actions.append(action)

        menu.addSeparator()
        show_all = menu.addAction("Alle Spalten einblenden")
        show_all.triggered.connect(self._show_all_columns)
        reset = menu.addAction("Standardansicht")
        reset.triggered.connect(self._reset_columns)
        self.columns_btn.setMenu(menu)

    def _set_column_visible(self, column: int, visible: bool) -> None:
        self.table.setColumnHidden(column, not visible)
        self._save_header_state()

    def _show_all_columns(self) -> None:
        for action in self._column_actions:
            action.setChecked(True)
        self._save_header_state()

    def _apply_default_columns(self) -> None:
        hidden_by_default = {self.columns.ACCEPT, self.columns.TYPE, self.columns.HINTS}
        for column, action in enumerate(self._column_actions):
            visible = column not in hidden_by_default
            self.table.setColumnHidden(column, not visible)
            action.blockSignals(True)
            action.setChecked(visible)
            action.blockSignals(False)
        for column, width in self._default_column_widths.items():
            self.table.setColumnWidth(column, width)

    def _reset_columns(self) -> None:
        self._apply_default_columns()
        self._save_header_state()

    def _restore_header_state(self) -> None:
        restored = False
        if self.settings is not None:
            state = self.settings.value(self._HEADER_STATE_KEY)
            if state is not None:
                try:
                    restored = bool(self.table.horizontalHeader().restoreState(state))
                except (TypeError, ValueError):
                    restored = False
        if not restored:
            self._apply_default_columns()

        for column, action in enumerate(self._column_actions):
            action.blockSignals(True)
            action.setChecked(not self.table.isColumnHidden(column))
            action.blockSignals(False)

    def _save_header_state(self, *_args) -> None:
        if self.settings is None:
            return
        self.settings.setValue(
            self._HEADER_STATE_KEY,
            self.table.horizontalHeader().saveState(),
        )

    @property
    def action_buttons(self) -> tuple:
        return (
            self.add_files_btn,
            self.add_folder_btn,
            self.resolve_btn,
            self.manual_series_search_btn,
            self.manual_movie_search_btn,
            self.show_all_candidates_btn,
            self.edit_search_btn,
            self.accept_selected_btn,
            self.accept_safe_btn,
            self.reject_selected_btn,
            self.rename_btn,
            self.remove_btn,
            self.clear_btn,
        )

    @property
    def lockable_buttons(self) -> tuple:
        return (
            self.resolve_btn,
            self.manual_series_search_btn,
            self.manual_movie_search_btn,
            self.show_all_candidates_btn,
            self.edit_search_btn,
            self.accept_selected_btn,
            self.accept_safe_btn,
            self.reject_selected_btn,
            self.rename_btn,
            self.remove_btn,
            self.clear_btn,
        )

    def set_busy(self, busy: bool) -> None:
        self.add_files_btn.setEnabled(True)
        self.add_folder_btn.setEnabled(True)
        for button in self.lockable_buttons:
            button.setEnabled(not busy)
