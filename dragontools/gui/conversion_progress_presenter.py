# -*- coding: utf-8 -*-
"""Progress event coordinator; selector and display rendering live in dedicated helpers."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from ..core.result_status import POSTPROCESS_PENDING_ICON
from .conversion_progress_display import ConversionProgressDisplay, eta_text as _eta
from .conversion_progress_focus import ConversionProgressFocusController, PROGRESS_FOCUS_ACTIVE_TOTAL


class ConversionProgressPresenter:
    def __init__(self, *, state, ui, log: Callable, refresh_queue: Callable[[], None],
                 set_file_list_item_text: Callable[[str, str], None], mark_file_started: Callable[[str], None] | None = None) -> None:
        self._state, self._ui, self._log = state, ui, log
        self._refresh_queue = refresh_queue
        self._set_file_list_item_text = set_file_list_item_text
        self._mark_file_started = mark_file_started or (lambda _path: None)
        self._last_queue_refresh_at = 0.0
        self._focus = ConversionProgressFocusController(state=state, ui=ui, log=log, on_changed=self.update_file_progress_display)
        self._display = ConversionProgressDisplay(state=state, ui=ui, focus=self._focus)
        self.connect_focus_selector()

    @property
    def last_queue_refresh_at(self) -> float:
        return self._last_queue_refresh_at

    @last_queue_refresh_at.setter
    def last_queue_refresh_at(self, value: float) -> None:
        self._last_queue_refresh_at = float(value)

    def reset(self, file_count: int) -> None:
        self._state.reset_for_run(file_count)
        self._state.current_log_path = None
        self._ui.curlog_btn.setEnabled(False)
        self._last_queue_refresh_at = 0.0
        self.clear_active_progress_display(clear_widgets=True)

    def on_total_progress(self, pct: int) -> None:
        self._ui.progress_bar.setValue(pct)
        n, done, worker = self._state.total_files, len(self._state.completed_inputs), self._state.thread
        if n <= 0:
            return
        if worker and hasattr(worker, "active_file_count"):
            self._ui.total_lbl.setText(f"Gesamt: {done}/{n} fertig · {int(worker.active_file_count())} aktiv")
        else:
            current = min(done + 1, n) if done < n else n
            self._ui.total_lbl.setText(f"Gesamt: Datei {current}/{n}")

    def on_file_progress(self, path: str, pct: int, eta_s) -> None:
        state, path_str = self._state, str(path)
        pct = max(0, min(100, int(pct or 0)))
        self._mark_file_started(path_str)
        eta_str = self.format_eta(eta_s)
        postprocess_pending = pct >= 100 and path_str in getattr(
            state, "pending_postprocess_inputs", set()
        )
        if postprocess_pending:
            self._set_file_list_item_text(
                path_str, f"{POSTPROCESS_PENDING_ICON}  {Path(path_str).name}"
            )
        else:
            self._set_file_list_item_text(
                path_str,
                f"⏳ {eta_str}  {Path(path_str).name}" if eta_str else f"⏳ {Path(path_str).name}",
            )
        if pct >= 100:
            state.active_file_progress.pop(path_str, None); state.active_file_eta.pop(path_str, None)
            if state.progress_focus_path == path_str: state.progress_focus_path = None
        else:
            state.active_file_progress[path_str] = pct; state.active_file_eta[path_str] = eta_s
        self.update_file_progress_display(changed_path=path_str, changed_pct=pct, changed_eta=eta_s)
        self._update_total_from_file_progress(pct)
        self.refresh_queue_after_file_progress(pct)

    def _update_total_from_file_progress(self, pct: int) -> None:
        state, ui = self._state, self._ui
        n, done, worker = state.total_files or 1, len(state.completed_inputs), state.thread
        total_pct = int(worker.aggregate_progress_percent()) if worker and hasattr(worker, "aggregate_progress_percent") else int(((done + pct / 100.0) / n) * 100)
        total_pct = max(state.last_total_pct, min(99 if done < n else 100, total_pct))
        state.last_total_pct = total_pct; ui.progress_bar.setValue(total_pct)
        if worker and hasattr(worker, "active_file_count"):
            ui.total_lbl.setText(f"Gesamt: {done}/{n} fertig · {int(worker.active_file_count())} aktiv")
        else:
            ui.total_lbl.setText(f"Gesamt: Datei {done + 1}/{n}")

    def on_file_result_cleanup(self, input_path: str, _output_path: str, _status: str) -> None:
        path = str(input_path)
        self._state.active_file_progress.pop(path, None); self._state.active_file_eta.pop(path, None)
        if self._state.progress_focus_path == path: self._state.progress_focus_path = None
        self.update_file_progress_display()

    def refresh_queue_after_file_progress(self, pct: int) -> None:
        total = int(self._state.total_files or self._ui.file_list.count() or 0)
        now = time.monotonic()
        if total < 80 or pct >= 100 or now - self._last_queue_refresh_at >= 0.35:
            self._last_queue_refresh_at = now
            self._refresh_queue()

    def connect_focus_selector(self) -> None: self._focus.connect()
    def on_progress_focus_changed(self) -> None: self._focus.changed()
    def clear_active_progress_display(self, *args, clear_widgets: bool = False) -> None: self._display.clear(clear_widgets=clear_widgets)
    def update_file_progress_display(self, **kwargs) -> None: self._display.update(**kwargs)
    def show_single_file_progress(self, path: str, pct: int) -> None: self._display.show_single(path, pct)
    def sync_progress_focus_combo(self, active: dict[str, int]) -> None: self._focus.sync(active)
    def progress_display_sort_key(self, path: str): return self._focus.sort_key(path)
    def progress_combo_label(self, path: str) -> str: return self._focus.combo_label(path)
    @classmethod
    def format_eta(cls, eta_s) -> str: return ConversionProgressDisplay.format_eta(eta_s)
    @staticmethod
    def eta_value(eta_s): return ConversionProgressDisplay.eta_value(eta_s)
    def set_file_bar_format(self, text: str) -> None: self._display.set_bar_format(text)
