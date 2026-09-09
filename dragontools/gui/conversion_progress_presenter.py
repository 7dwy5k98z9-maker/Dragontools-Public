# -*- coding: utf-8 -*-
"""Fortschrittsdarstellung für Conversion- und Parallel-Worker.

Die Klasse besitzt ausschließlich Präsentations- und Fortschrittszustand. Sie
startet keine Worker und entscheidet nicht über Encoder-/Move-Logik.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable



def _eta(seconds) -> str:
    """Qt-unabhängige ETA-Formatierung (H:MM:SS bzw. MM:SS)."""
    if not seconds or seconds <= 0:
        return ""
    seconds = int(seconds)
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{sec:02d}" if hours else f"{minutes:02d}:{sec:02d}"


PROGRESS_FOCUS_ACTIVE_TOTAL = "__active_total__"


class ConversionProgressPresenter:
    def __init__(
        self,
        *,
        state,
        ui,
        log: Callable,
        refresh_queue: Callable[[], None],
        set_file_list_item_text: Callable[[str, str], None],
    ) -> None:
        self._state = state
        self._ui = ui
        self._log = log
        self._refresh_queue = refresh_queue
        self._set_file_list_item_text = set_file_list_item_text
        self._last_queue_refresh_at = 0.0
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
        ui = self._ui
        ui.progress_bar.setValue(pct)
        n = self._state.total_files
        done = len(self._state.completed_inputs)
        active_worker = self._state.thread
        if n <= 0:
            return
        if active_worker and hasattr(active_worker, "active_file_count"):
            active = int(active_worker.active_file_count())
            ui.total_lbl.setText(f"Gesamt: {done}/{n} fertig · {active} aktiv")
            return
        current = min(done + 1, n) if done < n else n
        ui.total_lbl.setText(f"Gesamt: Datei {current}/{n}")

    def on_file_progress(self, path: str, pct: int, eta_s) -> None:
        ui = self._ui
        state = self._state
        path_str = str(path)
        pct = max(0, min(100, int(pct or 0)))
        name = Path(path_str).name
        self.mark_job_journal_file_started(path_str)
        eta_str = self.format_eta(eta_s)
        label = f"⏳ {eta_str}  {name}" if eta_str else f"⏳ {name}"
        self._set_file_list_item_text(path_str, label)

        if pct >= 100:
            state.active_file_progress.pop(path_str, None)
            state.active_file_eta.pop(path_str, None)
            if state.progress_focus_path == path_str:
                state.progress_focus_path = None
        else:
            state.active_file_progress[path_str] = pct
            state.active_file_eta[path_str] = eta_s
        self.update_file_progress_display(
            changed_path=path_str,
            changed_pct=pct,
            changed_eta=eta_s,
        )

        n = state.total_files or 1
        done = len(state.completed_inputs)
        active_worker = state.thread
        if active_worker and hasattr(active_worker, "aggregate_progress_percent"):
            total_pct = int(active_worker.aggregate_progress_percent())
        else:
            total_pct = int(((done + pct / 100.0) / n) * 100)
        total_pct = max(state.last_total_pct, min(99 if done < n else 100, total_pct))
        state.last_total_pct = total_pct
        ui.progress_bar.setValue(total_pct)
        if active_worker and hasattr(active_worker, "active_file_count"):
            active = int(active_worker.active_file_count())
            ui.total_lbl.setText(f"Gesamt: {done}/{n} fertig · {active} aktiv")
        else:
            ui.total_lbl.setText(f"Gesamt: Datei {done + 1}/{n}")
        self.refresh_queue_after_file_progress(pct)

    def on_file_result_cleanup(self, input_path: str, _output_path: str, _status: str) -> None:
        path_str = str(input_path)
        self._state.active_file_progress.pop(path_str, None)
        self._state.active_file_eta.pop(path_str, None)
        if self._state.progress_focus_path == path_str:
            self._state.progress_focus_path = None
        self.update_file_progress_display()

    def refresh_queue_after_file_progress(self, pct: int) -> None:
        total = int(self._state.total_files or self._ui.file_list.count() or 0)
        if total < 80 or pct >= 100:
            self._last_queue_refresh_at = time.monotonic()
            self._refresh_queue()
            return
        now = time.monotonic()
        if now - self._last_queue_refresh_at >= 0.35:
            self._last_queue_refresh_at = now
            self._refresh_queue()

    def connect_focus_selector(self) -> None:
        combo = getattr(self._ui, "file_focus_combo", None)
        if combo is None:
            return
        try:
            combo.addItem("Aktive gesamt", PROGRESS_FOCUS_ACTIVE_TOTAL)
            combo.setVisible(False)
            signal = getattr(combo, "currentIndexChanged", None)
            connect = getattr(signal, "connect", None)
            if connect is not None:
                connect(lambda *_args: self.on_progress_focus_changed())
        except (AttributeError, RuntimeError, TypeError) as exc:
            self._log(f"⚠️ Fortschrittsauswahl konnte nicht initialisiert werden: {exc}", "warn")

    def on_progress_focus_changed(self) -> None:
        combo = getattr(self._ui, "file_focus_combo", None)
        if combo is None:
            return
        try:
            data = combo.currentData()
        except (AttributeError, RuntimeError, TypeError):
            data = PROGRESS_FOCUS_ACTIVE_TOTAL
        active = getattr(self._state, "active_file_progress", {})
        if data == PROGRESS_FOCUS_ACTIVE_TOTAL or data not in active:
            self._state.progress_focus_path = None
        else:
            self._state.progress_focus_path = str(data)
        self.update_file_progress_display()

    def clear_active_progress_display(self, *args, clear_widgets: bool = False) -> None:
        self._state.active_file_progress.clear()
        self._state.active_file_eta.clear()
        self._state.progress_focus_path = None
        combo = getattr(self._ui, "file_focus_combo", None)
        if combo is not None:
            try:
                combo.blockSignals(True)
                combo.clear()
                combo.addItem("Aktive gesamt", PROGRESS_FOCUS_ACTIVE_TOTAL)
                combo.setCurrentIndex(0)
                combo.setVisible(False)
                combo.blockSignals(False)
            except (AttributeError, RuntimeError, TypeError):
                try:
                    combo.blockSignals(False)
                except (AttributeError, RuntimeError, TypeError):
                    pass
        if clear_widgets:
            self._ui.file_lbl.setText("")
            self._ui.file_bar.setValue(0)
            self._ui.eta_lbl.setText("")
            self.set_file_bar_format("%p%  –  aktuelle Datei")

    def update_file_progress_display(
        self,
        *,
        changed_path: str | None = None,
        changed_pct: int | None = None,
        changed_eta=None,
    ) -> None:
        active = dict(getattr(self._state, "active_file_progress", {}) or {})
        self.sync_progress_focus_combo(active)

        if not active:
            if changed_path is not None and changed_pct is not None:
                self._ui.file_lbl.setText(f"⏳ {Path(changed_path).name}")
                self._ui.file_bar.setValue(max(0, min(100, int(changed_pct))))
                eta_str = self.format_eta(changed_eta)
                if eta_str:
                    self._ui.eta_lbl.setText(f"Restdauer aktuelle Datei: {eta_str}")
                elif int(changed_pct) >= 100:
                    self._ui.eta_lbl.setText("✅ Datei abgeschlossen")
                self.set_file_bar_format("%p%  –  aktuelle Datei")
            return

        if len(active) == 1:
            path, pct = next(iter(active.items()))
            self._state.progress_focus_path = path
            self.show_single_file_progress(path, pct)
            return

        focus_path = self._state.progress_focus_path
        if focus_path in active:
            self.show_single_file_progress(focus_path, active[focus_path])
            return

        self._state.progress_focus_path = None
        combined_pct = int(round(sum(active.values()) / max(1, len(active))))
        self.set_file_bar_format("%p%  –  aktive Dateien")
        self._ui.file_lbl.setText(f"⏳ {len(active)} Dateien parallel aktiv")
        self._ui.file_bar.setValue(combined_pct)
        eta_values = [
            value
            for value in (self.eta_value(v) for v in self._state.active_file_eta.values())
            if value is not None and value > 0
        ]
        if eta_values:
            self._ui.eta_lbl.setText(f"Restdauer aktive Dateien: bis ca. {_eta(max(eta_values))}")
        else:
            self._ui.eta_lbl.setText(f"Aktiver Fortschritt kombiniert: {combined_pct}%")

    def show_single_file_progress(self, path: str, pct: int) -> None:
        name = Path(path).name
        eta_str = self.format_eta(self._state.active_file_eta.get(path))
        self.set_file_bar_format("%p%  –  aktuelle Datei")
        self._ui.file_lbl.setText(f"⏳ {name}")
        self._ui.file_bar.setValue(max(0, min(100, int(pct))))
        if eta_str:
            self._ui.eta_lbl.setText(f"Restdauer aktuelle Datei: {eta_str}")
        else:
            self._ui.eta_lbl.setText(f"Aktueller Fortschritt: {max(0, min(100, int(pct)))}%")

    def sync_progress_focus_combo(self, active: dict[str, int]) -> None:
        combo = getattr(self._ui, "file_focus_combo", None)
        if combo is None:
            return
        show_selector = len(active) > 1
        try:
            was_visible = bool(combo.isVisible())
        except (AttributeError, RuntimeError, TypeError):
            was_visible = False
        if show_selector and not was_visible:
            self._state.progress_focus_path = None
        focus_data = self._state.progress_focus_path if self._state.progress_focus_path in active else None
        if not show_selector:
            focus_data = next(iter(active), None)
            self._state.progress_focus_path = focus_data

        items: list[tuple[str, str]] = []
        if show_selector:
            items.append(("Aktive gesamt", PROGRESS_FOCUS_ACTIVE_TOTAL))
        for path in sorted(active, key=self.progress_display_sort_key):
            items.append((self.progress_combo_label(path), path))

        current_data = focus_data or PROGRESS_FOCUS_ACTIVE_TOTAL
        try:
            combo.blockSignals(True)
            combo.clear()
            for label, data in items or [("Aktive gesamt", PROGRESS_FOCUS_ACTIVE_TOTAL)]:
                combo.addItem(label, data)
            index = 0
            for idx in range(combo.count()):
                if combo.itemData(idx) == current_data:
                    index = idx
                    break
            combo.setCurrentIndex(index)
            combo.setVisible(show_selector)
        except (AttributeError, RuntimeError, TypeError):
            pass
        finally:
            try:
                combo.blockSignals(False)
            except (AttributeError, RuntimeError, TypeError):
                pass

    def progress_display_sort_key(self, path: str):
        thread = self._state.thread
        if thread and hasattr(thread, "display_position_for_path"):
            try:
                idx, _total = thread.display_position_for_path(
                    path,
                    fallback_idx=999999,
                    fallback_total=max(1, self._state.total_files),
                )
                return (idx, Path(path).name.lower())
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        return (999999, Path(path).name.lower())

    def progress_combo_label(self, path: str) -> str:
        thread = self._state.thread
        prefix = ""
        if thread and hasattr(thread, "display_position_for_path"):
            try:
                idx, _total = thread.display_position_for_path(
                    path,
                    fallback_idx=0,
                    fallback_total=max(1, self._state.total_files),
                )
                if idx:
                    prefix = f"{idx}: "
            except (AttributeError, RuntimeError, TypeError, ValueError):
                prefix = ""
        return f"{prefix}{Path(path).name}"

    @classmethod
    def format_eta(cls, eta_s) -> str:
        value = cls.eta_value(eta_s)
        return _eta(value) if value is not None and value > 0 else ""

    @staticmethod
    def eta_value(eta_s):
        try:
            value = float(eta_s)
        except (TypeError, ValueError, OverflowError):
            return None
        return value if value > 0 else None

    def set_file_bar_format(self, text: str) -> None:
        try:
            self._ui.file_bar.setFormat(text)
        except (AttributeError, RuntimeError, TypeError):
            pass

    def mark_job_journal_file_started(self, path: str) -> None:
        journal = getattr(self._state, "job_journal", None)
        if journal is None:
            return
        current_paths = getattr(self._state, "job_journal_current_paths", set())
        if path in current_paths:
            return
        try:
            done = len(self._state.completed_inputs)
            index = done + 1
            total = self._state.total_files
            thread = self._state.thread
            if thread and hasattr(thread, "display_position_for_path"):
                index, total = thread.display_position_for_path(
                    path,
                    fallback_idx=index,
                    fallback_total=total,
                )
            journal.start_file(path, index=index, total=total)
        except (OSError, RuntimeError, TypeError, ValueError, AttributeError) as exc:
            self._log(f"⚠️ Job-Journal konnte Dateistart nicht speichern: {exc}", "warn")
            return
        self._state.job_journal_current_path = path
        current_paths.add(path)
