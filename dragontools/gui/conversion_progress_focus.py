from __future__ import annotations

from pathlib import Path

PROGRESS_FOCUS_ACTIVE_TOTAL = "__active_total__"


class ConversionProgressFocusController:
    def __init__(self, *, state, ui, log, on_changed) -> None:
        self._state = state
        self._ui = ui
        self._log = log
        self._on_changed = on_changed

    def connect(self) -> None:
        combo = getattr(self._ui, "file_focus_combo", None)
        if combo is None:
            return
        try:
            combo.addItem("Aktive gesamt", PROGRESS_FOCUS_ACTIVE_TOTAL)
            combo.setVisible(False)
            connect = getattr(getattr(combo, "currentIndexChanged", None), "connect", None)
            if connect is not None:
                connect(lambda *_args: self.changed())
        except (AttributeError, RuntimeError, TypeError) as exc:
            self._log(f"⚠️ Fortschrittsauswahl konnte nicht initialisiert werden: {exc}", "warn")

    def changed(self) -> None:
        combo = getattr(self._ui, "file_focus_combo", None)
        if combo is None:
            return
        try:
            data = combo.currentData()
        except (AttributeError, RuntimeError, TypeError):
            data = PROGRESS_FOCUS_ACTIVE_TOTAL
        active = getattr(self._state, "active_file_progress", {})
        self._state.progress_focus_path = None if data == PROGRESS_FOCUS_ACTIVE_TOTAL or data not in active else str(data)
        self._on_changed()

    def clear(self) -> None:
        combo = getattr(self._ui, "file_focus_combo", None)
        if combo is None:
            return
        try:
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("Aktive gesamt", PROGRESS_FOCUS_ACTIVE_TOTAL)
            combo.setCurrentIndex(0)
            combo.setVisible(False)
        except (AttributeError, RuntimeError, TypeError):
            pass
        finally:
            try:
                combo.blockSignals(False)
            except (AttributeError, RuntimeError, TypeError):
                pass

    def sync(self, active: dict[str, int]) -> None:
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
        items = [("Aktive gesamt", PROGRESS_FOCUS_ACTIVE_TOTAL)] if show_selector else []
        items.extend((self.combo_label(path), path) for path in sorted(active, key=self.sort_key))
        current_data = focus_data or PROGRESS_FOCUS_ACTIVE_TOTAL
        try:
            combo.blockSignals(True)
            combo.clear()
            for label, data in items or [("Aktive gesamt", PROGRESS_FOCUS_ACTIVE_TOTAL)]:
                combo.addItem(label, data)
            index = next((idx for idx in range(combo.count()) if combo.itemData(idx) == current_data), 0)
            combo.setCurrentIndex(index)
            combo.setVisible(show_selector)
        except (AttributeError, RuntimeError, TypeError):
            pass
        finally:
            try:
                combo.blockSignals(False)
            except (AttributeError, RuntimeError, TypeError):
                pass

    def sort_key(self, path: str):
        thread = self._state.thread
        if thread and hasattr(thread, "display_position_for_path"):
            try:
                idx, _total = thread.display_position_for_path(path, fallback_idx=999999, fallback_total=max(1, self._state.total_files))
                return idx, Path(path).name.lower()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        return 999999, Path(path).name.lower()

    def combo_label(self, path: str) -> str:
        thread = self._state.thread
        prefix = ""
        if thread and hasattr(thread, "display_position_for_path"):
            try:
                idx, _total = thread.display_position_for_path(path, fallback_idx=0, fallback_total=max(1, self._state.total_files))
                if idx:
                    prefix = f"{idx}: "
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        return f"{prefix}{Path(path).name}"
