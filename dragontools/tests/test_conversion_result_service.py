from __future__ import annotations

from types import SimpleNamespace


class _Button:
    def __init__(self):
        self.enabled = None
        self.text = ""

    def setEnabled(self, value):
        self.enabled = bool(value)

    def setText(self, value):
        self.text = value


class _Label:
    def __init__(self):
        self.text = ""

    def setText(self, value):
        self.text = value


class _Bar:
    def __init__(self):
        self.value = None

    def setValue(self, value):
        self.value = int(value)


class _UI:
    def __init__(self):
        self.pause_btn = _Button()
        self.abort_btn = _Button()
        self.progress_bar = _Bar()
        self.file_lbl = _Label()
        self.eta_lbl = _Label()
        self.shut_cb = SimpleNamespace(isChecked=lambda: False)
        self.file_list = object()


def _service():
    from dragontools.gui.conversion_result_service import ConversionResultService
    from dragontools.gui.conversion_session_state import ConversionSessionState

    state = ConversionSessionState()
    ui = _UI()
    logs = []
    move_calls = []
    start_enabled = []
    queue_edit = []
    refreshes = []
    clears = []

    service = ConversionResultService(
        state=state,
        ui=ui,
        log=lambda msg, level="info": logs.append((level, msg)),
        start_move=lambda files, thread: move_calls.append((list(files), thread)),
        set_start_enabled=start_enabled.append,
        set_queue_edit=queue_edit.append,
        refresh_queue=lambda: refreshes.append(True),
        clear=lambda: clears.append(True),
        confirm_shutdown=lambda: None,
        parent_widget=None,
    )
    service._show_replacement_reminders = lambda: None
    return service, state, logs, move_calls, start_enabled, queue_edit, refreshes, clears


def test_sofort_abbruch_fragt_und_startet_move_fuer_erfolgreiche_dateien():
    service, state, logs, move_calls, start_enabled, queue_edit, _refreshes, clears = _service()
    thread = SimpleNamespace(abort_requested=True, abort_type="sofort")
    state.thread = thread
    state.fertig.update({"out1.mkv", "out2.mkv"})
    service._confirm_move_after_abort = lambda count: count == 2

    service.on_finished()

    assert len(move_calls) == 1
    assert set(move_calls[0][0]) == {"out1.mkv", "out2.mkv"}
    assert move_calls[0][1] is thread
    assert state.thread is None
    assert clears == []
    assert start_enabled == []
    assert queue_edit == []
    assert any("werden jetzt verschoben" in msg for _level, msg in logs)


def test_abbruch_nach_datei_fragt_und_startet_move_fuer_erfolgreiche_dateien():
    service, state, _logs, move_calls, _start_enabled, _queue_edit, _refreshes, clears = _service()
    thread = SimpleNamespace(abort_requested=True, abort_type="nach_datei")
    state.thread = thread
    state.fertig.add("out1.mkv")
    service._confirm_move_after_abort = lambda count: True

    service.on_finished()

    assert move_calls == [(["out1.mkv"], thread)]
    assert clears == []


def test_abbruch_ohne_move_wunsch_finalisiert_ohne_shutdown():
    service, state, logs, move_calls, start_enabled, queue_edit, _refreshes, clears = _service()
    thread = SimpleNamespace(abort_requested=True, abort_type="nach_datei")
    state.thread = thread
    state.fertig.add("out1.mkv")
    service._confirm_move_after_abort = lambda count: False
    finalize_calls = []
    service.finalize_run = lambda *args, **kwargs: finalize_calls.append((args, kwargs))

    service.on_finished()

    assert move_calls == []
    assert len(finalize_calls) == 1
    assert finalize_calls[0][1]["did_shutdown"] is True
    assert state.thread is None
    assert start_enabled == [True]
    assert queue_edit == [True]
    assert clears == []
    assert any("werden nicht verschoben" in msg for _level, msg in logs)


def test_abbruch_ohne_fertige_dateien_bleibt_altes_cleanup_verhalten():
    service, state, _logs, move_calls, start_enabled, queue_edit, _refreshes, clears = _service()
    thread = SimpleNamespace(abort_requested=True, abort_type="sofort")
    state.thread = thread

    service.on_finished()

    assert move_calls == []
    assert clears == [True]
    assert state.thread is None
    assert start_enabled == [True]
    assert queue_edit == [True]


def test_warning_result_is_terminal_but_not_successful(monkeypatch):
    service, state, _logs, _move_calls, _start_enabled, _queue_edit, refreshes, _clears = _service()
    input_path = "film.mkv"
    archive_path = "Archiv/film.mkv"
    state.thread = SimpleNamespace(
        _failure_details={
            input_path: {
                "message": "Ausgabedatei ist größer als erlaubt; Original wurde nicht ersetzt.",
                "pipeline": "standard",
                "container": "mkv",
                "strategy": "standard",
            }
        }
    )
    monkeypatch.setattr(service, "_set_file_list_item_text", lambda *_args: None)

    service.on_file_result(input_path, archive_path, "\u26a0\ufe0f")

    assert input_path in state.completed_inputs
    assert archive_path not in state.fertig
    assert state.run_results[input_path]["status"] == "error"
    assert state.run_results[input_path]["output_path"] == ""
    assert "größer" in state.run_results[input_path]["message"]
    assert refreshes


def test_postprocess_pending_result_is_not_terminal(monkeypatch):
    service, state, _logs, _move_calls, _start_enabled, _queue_edit, refreshes, _clears = _service()
    monkeypatch.setattr(service, "_set_file_list_item_text", lambda *_args: None)

    service.on_file_result("film.mkv", "film.mkv", "🧩")

    assert "film.mkv" not in state.completed_inputs
    assert "film.mkv" not in state.fertig
    assert "film.mkv" in state.pending_postprocess_inputs
    assert refreshes


def test_finished_waits_for_pending_postprocess_before_move(monkeypatch):
    service, state, logs, move_calls, _start_enabled, _queue_edit, _refreshes, _clears = _service()
    thread = SimpleNamespace(abort_requested=False, _sidecar_outputs={}, _postprocess_outputs={})
    state.thread = thread
    state.pending_postprocess_inputs.add("film.mkv")
    state.fertig.clear()
    service._ui.move_cb = SimpleNamespace(isChecked=lambda: True)
    monkeypatch.setattr(service, "_set_file_list_item_text", lambda *_args: None)

    service.on_finished()

    assert move_calls == []
    assert state.thread is thread
    assert state.finish_waiting_for_postprocess is True
    assert any("Post-Processing" in msg for _level, msg in logs)

    service.on_file_result("film.mkv", "out.mkv", "✅")

    assert move_calls == [(["out.mkv"], thread)]
    assert state.thread is None


def test_success_result_without_live_thread_still_records_output(monkeypatch):
    service, state, _logs, _move_calls, _start_enabled, _queue_edit, refreshes, _clears = _service()
    state.thread = None
    monkeypatch.setattr(service, "_set_file_list_item_text", lambda *_args: None)

    service.on_file_result("film.mkv", "out.mkv", "✅")

    assert "film.mkv" in state.completed_inputs
    assert "out.mkv" in state.fertig
    assert state.sidecar_outputs_by_video["out.mkv"] == []
    assert state.postprocess_outputs_by_input["film.mkv"] == []
    assert refreshes


def test_finalize_run_skips_summary_dialog_when_shutdown_is_enabled():
    service, _state, logs, _move_calls, _start_enabled, _queue_edit, _refreshes, clears = _service()
    service._ui.shut_cb = SimpleNamespace(isChecked=lambda: True)
    shutdown_calls = []
    service._confirm_shutdown = lambda: shutdown_calls.append(True)
    service.log_run_summary = lambda *_args, **_kwargs: None

    def fail_if_dialog_opens(*_args, **_kwargs):
        raise AssertionError("Abschlussdialog darf bei Herunterfahren nicht öffnen")

    service._show_run_summary_dialog = fail_if_dialog_opens

    service.finalize_run(SimpleNamespace(), move_log=[], move_ok=0, move_errors=0)

    assert clears == [True]
    assert shutdown_calls == [True]
    assert any("Abschlussbericht" in msg for _level, msg in logs)


def test_finalize_run_shows_summary_dialog_when_shutdown_is_disabled():
    service, _state, _logs, _move_calls, _start_enabled, _queue_edit, _refreshes, clears = _service()
    dialog_calls = []
    shutdown_calls = []
    service._confirm_shutdown = lambda: shutdown_calls.append(True)
    service.log_run_summary = lambda *_args, **_kwargs: None
    service._show_run_summary_dialog = lambda *_args, **_kwargs: dialog_calls.append(True) or []

    service.finalize_run(SimpleNamespace(), move_log=[], move_ok=0, move_errors=0)

    assert dialog_calls == [True]
    assert clears == [True]
    assert shutdown_calls == []


def test_finalize_run_shows_replacement_reminders_before_summary_when_shutdown_disabled():
    service, _state, _logs, _move_calls, _start_enabled, _queue_edit, _refreshes, _clears = _service()
    calls = []
    service.log_run_summary = lambda *_args, **_kwargs: None
    service._show_replacement_reminders = lambda: calls.append("reminders")
    service._show_run_summary_dialog = lambda *_args, **_kwargs: calls.append("summary") or []

    service.finalize_run(SimpleNamespace(), move_log=[], move_ok=0, move_errors=0)

    assert calls == ["reminders", "summary"]


def test_finalize_run_does_not_show_replacement_reminders_when_shutdown_is_enabled():
    service, _state, _logs, _move_calls, _start_enabled, _queue_edit, _refreshes, _clears = _service()
    service._ui.shut_cb = SimpleNamespace(isChecked=lambda: True)
    calls = []
    service.log_run_summary = lambda *_args, **_kwargs: None
    service._show_replacement_reminders = lambda: calls.append("reminders")
    service._show_run_summary_dialog = lambda *_args, **_kwargs: calls.append("summary") or []

    service.finalize_run(SimpleNamespace(), move_log=[], move_ok=0, move_errors=0)

    assert calls == []


def test_replacement_reminder_confirmation_logs_exact_deleted_id(monkeypatch):
    service, _state, logs, *_rest = _service()
    # _service() unterdrückt Dialoge für die übrigen Tests; hier die echte Methode verwenden.
    del service.__dict__["_show_replacement_reminders"]

    snapshots = iter([
        [{"id": "#20260905-091756-001"}],
        [],
    ])
    monkeypatch.setattr(
        "dragontools.core.replacement_reminders.list_replacement_reminders",
        lambda: next(snapshots),
    )
    import sys
    import types

    fake_dialog = types.ModuleType("dragontools.gui.replacement_reminder_dialog")
    fake_dialog.show_pending_replacement_reminders = lambda _parent: 1
    monkeypatch.setitem(sys.modules, "dragontools.gui.replacement_reminder_dialog", fake_dialog)

    service._show_replacement_reminders()

    assert any(
        "aus der Erinnerungsliste gelöscht: #20260905-091756-001" in message
        for _level, message in logs
    )
