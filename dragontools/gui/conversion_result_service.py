# -*- coding: utf-8 -*-
"""Fassade für Datei-Ergebnisse und Abschluss eines Konvertierungslaufs."""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from .conversion_result_file_events import ConversionResultFileEventsMixin
from .conversion_result_finish import ConversionResultFinishMixin
from .conversion_run_finalizer import ConversionRunFinalizerMixin
from .conversion_session_state import ConversionSessionState

if TYPE_CHECKING:
    from .convert_widget_layout import ConvertWidgetUI


class ConversionResultService(
    ConversionResultFileEventsMixin,
    ConversionResultFinishMixin,
    ConversionRunFinalizerMixin,
):
    """Schmale DI-Fassade; Result-, Finish- und Finalizerlogik sind getrennt."""

    def __init__(
        self,
        *,
        state: ConversionSessionState,
        ui: ConvertWidgetUI,
        log: Callable,
        start_move: Callable,
        set_start_enabled: Callable,
        set_queue_edit: Callable,
        refresh_queue: Callable,
        clear: Callable,
        confirm_shutdown: Callable,
        parent_widget=None,
        requeue_files: Callable[[list[str]], None] | None = None,
    ) -> None:
        self._state = state
        self._ui = ui
        self._log = log
        self._start_move = start_move
        self._set_start_enabled = set_start_enabled
        self._set_queue_edit = set_queue_edit
        self._refresh_queue = refresh_queue
        self._clear = clear
        self._confirm_shutdown = confirm_shutdown
        self._parent_widget = parent_widget
        self._requeue_files = requeue_files
        self._on_file_progress_impl: Callable | None = None

    def set_file_progress_handler(self, handler: Callable) -> None:
        self._on_file_progress_impl = handler

    def on_file_progress(self, path: str, pct: int, eta_s) -> None:
        if self._on_file_progress_impl is not None:
            self._on_file_progress_impl(path, pct, eta_s)
