from __future__ import annotations

from pathlib import Path

from ..core.result_status import POSTPROCESS_PENDING_ICON


def eta_text(seconds) -> str:
    if not seconds or seconds <= 0:
        return ""
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{sec:02d}" if hours else f"{minutes:02d}:{sec:02d}"


class ConversionProgressDisplay:
    def __init__(self, *, state, ui, focus) -> None:
        self._state = state
        self._ui = ui
        self._focus = focus

    def clear(self, *, clear_widgets: bool = False) -> None:
        self._state.active_file_progress.clear()
        self._state.active_file_eta.clear()
        self._state.progress_focus_path = None
        self._focus.clear()
        if clear_widgets:
            self._ui.file_lbl.setText("")
            self._ui.file_bar.setValue(0)
            self._ui.eta_lbl.setText("")
            self.set_bar_format("%p%  –  aktuelle Datei")

    def update(self, *, changed_path: str | None = None, changed_pct: int | None = None, changed_eta=None) -> None:
        active = dict(getattr(self._state, "active_file_progress", {}) or {})
        self._focus.sync(active)
        if not active:
            self._show_completed_change(changed_path, changed_pct, changed_eta)
            return
        if len(active) == 1:
            path, pct = next(iter(active.items()))
            self._state.progress_focus_path = path
            self.show_single(path, pct)
            return
        focus_path = self._state.progress_focus_path
        if focus_path in active:
            self.show_single(focus_path, active[focus_path])
            return
        self._state.progress_focus_path = None
        combined_pct = int(round(sum(active.values()) / max(1, len(active))))
        self.set_bar_format("%p%  –  aktive Dateien")
        self._ui.file_lbl.setText(f"⏳ {len(active)} Dateien parallel aktiv")
        self._ui.file_bar.setValue(combined_pct)
        values = [v for v in (self.eta_value(x) for x in self._state.active_file_eta.values()) if v is not None and v > 0]
        self._ui.eta_lbl.setText(
            f"Restdauer aktive Dateien: bis ca. {eta_text(max(values))}" if values
            else f"Aktiver Fortschritt kombiniert: {combined_pct}%"
        )

    def _show_completed_change(self, path, pct, eta) -> None:
        if path is None or pct is None:
            return
        pct = max(0, min(100, int(pct)))
        postprocess_pending = (
            pct >= 100
            and str(path) in getattr(self._state, "pending_postprocess_inputs", set())
        )
        if postprocess_pending:
            self._ui.file_lbl.setText(f"{POSTPROCESS_PENDING_ICON} {Path(path).name}")
        else:
            self._ui.file_lbl.setText(f"⏳ {Path(path).name}")
        self._ui.file_bar.setValue(pct)
        eta_str = self.format_eta(eta)
        if postprocess_pending:
            self._ui.eta_lbl.setText("Video fertig · NFO/Trickplay wird erstellt")
        elif eta_str:
            self._ui.eta_lbl.setText(f"Restdauer aktuelle Datei: {eta_str}")
        elif pct >= 100:
            self._ui.eta_lbl.setText("✅ Datei abgeschlossen")
        self.set_bar_format("%p%  –  aktuelle Datei")

    def show_single(self, path: str, pct: int) -> None:
        pct = max(0, min(100, int(pct)))
        eta_str = self.format_eta(self._state.active_file_eta.get(path))
        self.set_bar_format("%p%  –  aktuelle Datei")
        self._ui.file_lbl.setText(f"⏳ {Path(path).name}")
        self._ui.file_bar.setValue(pct)
        self._ui.eta_lbl.setText(f"Restdauer aktuelle Datei: {eta_str}" if eta_str else f"Aktueller Fortschritt: {pct}%")

    @classmethod
    def format_eta(cls, eta_s) -> str:
        value = cls.eta_value(eta_s)
        return eta_text(value) if value is not None and value > 0 else ""

    @staticmethod
    def eta_value(eta_s):
        try:
            value = float(eta_s)
        except (TypeError, ValueError, OverflowError):
            return None
        return value if value > 0 else None

    def set_bar_format(self, text: str) -> None:
        try:
            self._ui.file_bar.setFormat(text)
        except (AttributeError, RuntimeError, TypeError):
            pass
