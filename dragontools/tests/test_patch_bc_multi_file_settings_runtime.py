from __future__ import annotations

import pytest

pytest.importorskip("PyQt6")

from types import SimpleNamespace

from dragontools.gui.convert_widget_override_dialog import ConvertWidgetOverrideDialogHelper


class _ValueControl:
    def __init__(self, value):
        self._value = value

    def currentData(self):
        return self._value

    def value(self):
        return self._value

    def isChecked(self):
        return bool(self._value)


class _Thread:
    def __init__(self, rejected: set[str] | None = None):
        self.rejected = rejected or set()
        self.calls: list[tuple[str, dict]] = []

    def update_override(self, path: str, override: dict) -> bool:
        self.calls.append((path, dict(override)))
        return path not in self.rejected


def _controls(*, track_analysis_ok: bool = False) -> dict:
    return {
        "track_analysis_ok": track_analysis_ok,
        "processing_combo": _ValueControl("normal"),
        "encoder_override": object(),
        "audio_mode_combo": _ValueControl("auto"),
        "subtitle_mode_combo": _ValueControl("auto"),
        "audio_rows": [],
        "subtitle_rows": [],
        "drc_mode_combo": _ValueControl("inherit"),
        "drc_scale_spin": _ValueControl(1.0),
        "loudnorm_mode_combo": _ValueControl("inherit"),
        "loudnorm_i_spin": _ValueControl(-16.0),
        "imax_cb": _ValueControl(True),
        "dv_combo": _ValueControl(None),
        "hdrplus_combo": _ValueControl(None),
        "sdr_hdr_combo": _ValueControl(True),
        "hdrgen_combo": _ValueControl(False),
    }


def test_batch_override_persists_to_every_pending_file_and_preserves_private_state(monkeypatch):
    first = "first.mkv"
    second = "second.mkv"
    thread = _Thread()
    state = SimpleNamespace(
        file_overrides={
            first: {"encoder_profile": {"key": "film"}, "future_flag": "first"},
            second: {"encoder_profile": {"key": "anime"}, "future_flag": "second"},
        },
        preflight_rows_by_path={first: object(), second: object()},
        thread=thread,
    )
    updated: list[str] = []
    logs: list[tuple[str, str]] = []
    owner = SimpleNamespace(
        default_codec="h265",
        _guard_queue_edit_allowed=lambda _action: True,
        _log=lambda *_args: None,
        update_queue_label=lambda path: updated.append(path),
        log_message=lambda message, level="info": logs.append((message, level)),
    )
    helper = ConvertWidgetOverrideDialogHelper(owner)
    monkeypatch.setattr(helper._encoder_override, "persist_group", lambda _ov, _controls: None)

    helper._persist_override_result(
        [first, second],
        state,
        {"audio_mode": "auto", "subtitle_mode": "auto"},
        _controls(track_analysis_ok=False),
    )

    assert [path for path, _override in thread.calls] == [first, second]
    assert updated == [first, second]
    assert state.file_overrides[first]["encoder_profile"] == {"key": "film"}
    assert state.file_overrides[second]["encoder_profile"] == {"key": "anime"}
    assert state.file_overrides[first]["future_flag"] == "first"
    assert state.file_overrides[second]["future_flag"] == "second"
    assert state.file_overrides[first]["imax"] is True
    assert state.file_overrides[second]["sdr_hdr"] is True
    assert state.file_overrides[first]["generate_hdr10plus"] is False
    assert state.preflight_rows_by_path == {}
    assert logs[-1][0] == "Datei-Einstellungen angewendet: 2 Datei(en)"


def test_batch_override_rejection_does_not_mutate_running_file(monkeypatch):
    first = "pending.mkv"
    second = "running.mkv"
    thread = _Thread({second})
    state = SimpleNamespace(
        file_overrides={
            first: {"encoder_profile": {"key": "film"}},
            second: {"encoder_profile": {"key": "anime"}, "imax": False},
        },
        preflight_rows_by_path={first: object(), second: object()},
        thread=thread,
    )
    warnings: list[tuple] = []
    owner = SimpleNamespace(
        default_codec="h265",
        _guard_queue_edit_allowed=lambda _action: True,
        _log=lambda *_args: None,
        update_queue_label=lambda _path: None,
        log_message=lambda *_args: None,
    )
    helper = ConvertWidgetOverrideDialogHelper(owner)
    monkeypatch.setattr(helper._encoder_override, "persist_group", lambda _ov, _controls: None)
    monkeypatch.setattr(
        "dragontools.gui.convert_widget_override_dialog.QMessageBox.warning",
        lambda *args: warnings.append(args),
    )

    helper._persist_override_result(
        [first, second],
        state,
        {"audio_mode": "auto", "subtitle_mode": "auto"},
        _controls(track_analysis_ok=False),
    )

    assert state.file_overrides[first]["imax"] is True
    assert state.file_overrides[second] == {"encoder_profile": {"key": "anime"}, "imax": False}
    assert first not in state.preflight_rows_by_path
    assert second in state.preflight_rows_by_path
    assert warnings and "running.mkv" in warnings[-1][-1]
