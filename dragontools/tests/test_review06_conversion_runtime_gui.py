from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest


class _Button:
    def __init__(self):
        self.enabled = None
        self.text = ""
        self.tooltip = ""

    def setEnabled(self, value):
        self.enabled = bool(value)

    def setText(self, value):
        self.text = str(value)

    def setToolTip(self, value):
        self.tooltip = str(value)


class _Bar:
    def __init__(self):
        self.value = None
        self.format = ""

    def setValue(self, value):
        self.value = int(value)

    def setFormat(self, value):
        self.format = str(value)


class _Label:
    def __init__(self):
        self.text = ""

    def setText(self, value):
        self.text = str(value)


class _Check:
    def __init__(self, checked=False):
        self._checked = bool(checked)

    def isChecked(self):
        return self._checked


class _Combo:
    def __init__(self, text="medium"):
        self._text = text

    def currentText(self):
        return self._text


class _Spin:
    def __init__(self, value=22):
        self._value = value

    def value(self):
        return self._value


class _Signal:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)


class _MoveWorker:
    def __init__(self):
        self._paused = False
        self.pause_calls = 0
        self.resume_calls = 0

    def isRunning(self):
        return True

    def pause(self):
        self._paused = True
        self.pause_calls += 1

    def resume(self):
        self._paused = False
        self.resume_calls += 1



def _install_minimal_pyqt(monkeypatch):
    pyqt = types.ModuleType("PyQt6")
    qtcore = types.ModuleType("PyQt6.QtCore")
    qtwidgets = types.ModuleType("PyQt6.QtWidgets")

    class _Settings:
        def __init__(self, *_args, **_kwargs):
            pass

        def value(self, _key, default=None, **_kwargs):
            return default

    class _Dialog:
        class DialogCode:
            Accepted = 1

    class _MessageBox:
        @staticmethod
        def warning(*_args, **_kwargs):
            return None

    qtcore.QSettings = _Settings
    qtwidgets.QDialog = _Dialog
    qtwidgets.QMessageBox = _MessageBox
    monkeypatch.setitem(sys.modules, "PyQt6", pyqt)
    monkeypatch.setitem(sys.modules, "PyQt6.QtCore", qtcore)
    monkeypatch.setitem(sys.modules, "PyQt6.QtWidgets", qtwidgets)
    return qtcore, qtwidgets


def test_pause_targets_active_move_worker_not_only_converter():
    from dragontools.gui.conversion_worker_lifecycle import ConversionWorkerLifecycle

    worker = _MoveWorker()
    state = SimpleNamespace(thread=None, move_thread=worker, retired_move_threads=[])
    ui = SimpleNamespace(pause_btn=_Button(), abort_btn=_Button())
    lifecycle = ConversionWorkerLifecycle(
        state=state,
        ui=ui,
        log=lambda *_a, **_k: None,
        set_start_enabled=lambda _value: None,
        refresh_queue=lambda: None,
        result_service=SimpleNamespace(),
        progress_presenter=SimpleNamespace(),
        default_codec="h265",
        collect_encoder_options=lambda: {},
    )

    lifecycle.toggle_pause()

    assert worker.pause_calls == 1
    assert ui.pause_btn.text == "▶ Fortsetzen"


def test_active_worker_ignores_destroyed_qt_wrapper_and_finds_move_worker():
    from dragontools.gui.conversion_worker_lifecycle import ConversionWorkerLifecycle

    class _Destroyed:
        def isRunning(self):
            raise RuntimeError("wrapped C/C++ object has been deleted")

    move_worker = _MoveWorker()
    state = SimpleNamespace(
        thread=_Destroyed(),
        move_thread=move_worker,
        retired_move_threads=[],
    )
    lifecycle = ConversionWorkerLifecycle(
        state=state,
        ui=SimpleNamespace(),
        log=lambda *_a, **_k: None,
        set_start_enabled=lambda _value: None,
        refresh_queue=lambda: None,
        result_service=SimpleNamespace(),
        progress_presenter=SimpleNamespace(),
        default_codec="h265",
        collect_encoder_options=lambda: {},
    )

    assert lifecycle.active_worker() is move_worker


def test_worker_start_exception_rolls_back_ui_and_job_journal(monkeypatch):
    from dragontools.gui.conversion_worker_lifecycle import ConversionWorkerLifecycle

    class _Journal:
        def __init__(self):
            self.statuses = []

        def finish_run(self, *, status):
            self.statuses.append(status)

    journal = _Journal()
    state = SimpleNamespace(
        current_log_path=None,
        job_journal=None,
        job_journal_current_path="x",
        job_journal_current_paths={"x"},
        thread=None,
        move_thread=None,
        retired_move_threads=[],
    )
    ui = SimpleNamespace(abort_btn=_Button(), progress_bar=_Bar(), curlog_btn=_Button(), pause_btn=_Button())
    starts = []

    class _Worker:
        log_file_path = "run.log"

        def start(self):
            raise RuntimeError("QThread refused to start")

    lifecycle = ConversionWorkerLifecycle(
        state=state,
        ui=ui,
        log=lambda *_a, **_k: None,
        set_start_enabled=starts.append,
        refresh_queue=lambda: None,
        result_service=SimpleNamespace(),
        progress_presenter=SimpleNamespace(refresh_queue_after_file_progress=lambda _pct: None),
        default_codec="h265",
        collect_encoder_options=lambda: {},
    )

    def _journal_start(*_args, **_kwargs):
        state.job_journal = journal
        return True

    monkeypatch.setattr(lifecycle, "start_job_journal", _journal_start)

    result = lifecycle.start_worker_ui_state(_Worker(), "start", mode="convert", files=["a.mkv"])

    assert result is False
    assert starts[-1] is True
    assert ui.abort_btn.enabled is False
    assert ui.pause_btn.enabled is False
    assert ui.curlog_btn.enabled is False
    assert state.current_log_path is None
    assert state.job_journal is None
    assert journal.statuses == ["start_failed"]


def test_conversion_finish_keeps_start_reservation_until_move_terminal():
    from dragontools.gui.conversion_result_finish import ConversionResultFinishMixin

    class _Harness(ConversionResultFinishMixin):
        pass

    ui = SimpleNamespace(
        pause_btn=_Button(),
        abort_btn=_Button(),
        file_lbl=_Label(),
        eta_lbl=_Label(),
        progress_bar=_Bar(),
        move_cb=_Check(True),
    )
    state = SimpleNamespace(
        pending_postprocess_inputs=set(),
        finish_waiting_for_postprocess=False,
        thread=SimpleNamespace(abort_requested=False),
        fertig={"out.mkv"},
        start_reserved=True,
    )
    h = _Harness()
    h._ui = ui
    h._state = state
    h._log = lambda *_a, **_k: None
    h._refresh_queue = lambda: None
    h._set_start_enabled = lambda _v: None
    h._set_queue_edit = lambda _v: None
    h.finalize_run = lambda *_a, **_k: None
    h._start_move = lambda *_a, **_k: True

    h.on_finished()

    assert state.thread is None
    assert state.start_reserved is True


def test_finalizer_summary_logger_failure_still_finishes_journal_and_clears_run():
    from dragontools.gui.conversion_run_finalizer import ConversionRunFinalizerMixin

    class _Journal:
        def __init__(self):
            self.status = None

        def finish_run(self, *, status):
            self.status = status

    class _Harness(ConversionRunFinalizerMixin):
        pass

    state = SimpleNamespace(
        summary_written=False,
        finalization_in_progress=False,
        move_report_log=[],
        move_ok_count=0,
        move_error_count=0,
        run_results={},
        job_journal=_Journal(),
        job_journal_current_path="a",
        job_journal_current_paths={"a"},
        watch_intake_blocked=False,
    )
    h = _Harness()
    h._state = state
    h._ui = SimpleNamespace(shut_cb=_Check(False))
    h._log = lambda *_a, **_k: None
    h._parent_widget = None
    h._notifications = None
    h._requeue_files = None
    cleared = []
    h._clear = lambda: cleared.append(True)
    h._confirm_shutdown = lambda: None
    h.log_run_summary = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("log disk full"))
    h._show_replacement_reminders = lambda: None
    h._show_run_summary_dialog = lambda *_a, **_k: []

    h.finalize_run(SimpleNamespace(abort_requested=False), move_log=[])

    assert cleared == [True]
    assert state.job_journal is None
    assert state.summary_written is True
    assert state.finalization_in_progress is False


def test_recovery_is_blocked_while_start_is_reserved(tmp_path):
    from dragontools.gui.convert_widget_recovery import ConvertWidgetRecoveryService

    video = tmp_path / "film.mkv"
    video.write_bytes(b"x")
    added = []
    file_list = SimpleNamespace(
        add_path=lambda p: added.append(p) or True,
        count=lambda: len(added),
    )
    state = SimpleNamespace(
        start_reserved=True,
        total_files=0,
        planned_targets={},
        sidecar_outputs_by_video={},
        restored_move_context={},
        file_overrides={},
        preflight_rows_by_path={},
    )
    service = ConvertWidgetRecoveryService(
        state=state,
        file_list=file_list,
        log=lambda *_a, **_k: None,
        active_worker=lambda: None,
        refresh_queue=lambda: None,
        update_label=lambda _path: None,
        default_codec="h265",
        get_subtitle_rules=lambda: {},
        overwrite_original=lambda: False,
        get_tools=lambda: {},
    )

    result = service.restore_job_files([str(video)])

    assert result == service.empty_result()
    assert added == []


def test_converter_config_deep_copies_nested_file_overrides():
    from dragontools.gui.conversion_worker_factory import ConversionConfigBuilder

    nested = {"film.mkv": {"encoder_profile": {"preset": "slow"}}}
    state = SimpleNamespace(file_overrides=nested)
    ui = SimpleNamespace(
        crf_spin=_Spin(),
        preset_combo=_Combo("medium"),
        scale_combo=_Combo("original"),
        over_cb=_Check(False),
        strip_cb=_Check(False),
    )
    builder = ConversionConfigBuilder(
        state=state,
        ui=ui,
        default_codec="h265",
        collect_encoder_options=lambda: {"encoder": "cpu"},
        get_target_paths=lambda: {},
        log=lambda *_a, **_k: None,
    )
    builder.subtitle_rules = lambda: {}

    config = builder.build_converter_config()
    config.file_overrides["film.mkv"]["encoder_profile"]["preset"] = "fast"

    assert state.file_overrides["film.mkv"]["encoder_profile"]["preset"] == "slow"


def test_dv_remux_options_deep_copy_nested_file_overrides_and_encoder_options():
    from dragontools.gui.conversion_worker_factory import ConversionConfigBuilder

    state = SimpleNamespace(file_overrides={"film.mkv": {"audio": {"mode": "copy"}}})
    ui = SimpleNamespace(
        crf_spin=_Spin(),
        preset_combo=_Combo("medium"),
        scale_combo=_Combo("original"),
        over_cb=_Check(False),
        strip_cb=_Check(False),
    )
    shared_encoder = {"encoder": "cpu", "advanced": {"threads": 4}}
    builder = ConversionConfigBuilder(
        state=state,
        ui=ui,
        default_codec="h265",
        collect_encoder_options=lambda: shared_encoder,
        get_target_paths=lambda: {},
        log=lambda *_a, **_k: None,
    )
    builder.subtitle_rules = lambda: {}

    options = builder.dv_remux_options()
    options["file_overrides"]["film.mkv"]["audio"]["mode"] = "aac"
    options["encoder_options"]["advanced"]["threads"] = 1

    assert state.file_overrides["film.mkv"]["audio"]["mode"] == "copy"
    assert shared_encoder["advanced"]["threads"] == 4


def test_queue_clear_during_active_conversion_preserves_completed_state():
    from dragontools.gui.convert_widget_queue_management import ConvertWidgetQueueManagementMixin

    class _Running:
        def isRunning(self):
            return True

    class _Queue:
        def __init__(self):
            self.calls = 0

        def clear(self):
            self.calls += 1

    class _Harness(ConvertWidgetQueueManagementMixin):
        pass

    h = _Harness()
    h._state = SimpleNamespace(
        completed_inputs={"done.mkv"},
        pending_remove_paths={"current.mkv"},
        thread=_Running(),
    )
    h._file_queue = _Queue()
    h._is_queue_blocking_move_active = lambda: False
    h._refresh_queue_window = lambda: None
    h._log = lambda *_a, **_k: None

    h._clear()

    assert h._file_queue.calls == 1
    assert h._state.completed_inputs == {"done.mkv"}
    assert "current.mkv" in h._state.pending_remove_paths


def test_success_logging_failure_does_not_turn_valid_output_into_worker_failure(tmp_path):
    from dragontools.worker.worker_result_service import WorkerConversionResultService

    output = tmp_path / "out.mkv"
    output.write_bytes(b"1234")
    emitted = []
    logs = []

    class _Logger:
        def file_done(self, **_kwargs):
            raise OSError("log target unavailable")

    runtime = SimpleNamespace(total_before=0, total_after=0, erfolgreich=0, fehlgeschlagen=0)
    service = WorkerConversionResultService(
        logger=_Logger(),
        runtime_state=runtime,
        overwrite_original=False,
        event_emit=lambda _event: None,
        file_progress_emit=lambda *_args: None,
        file_result_emit=lambda *args: emitted.append(args),
        log=lambda *args: logs.append(args),
        failure_details={},
    )
    ctx = SimpleNamespace(
        input_path="in.mkv",
        output_path=str(output),
        final_output_path=str(output),
        size_before=10,
        start_ts=0.0,
    )

    service.finalize_success(ctx)

    assert runtime.erfolgreich == 1
    assert runtime.fehlgeschlagen == 0
    assert emitted[-1] == ("in.mkv", str(output), "✅")
    assert any("Logging" in str(item) for row in logs for item in row)


def _import_regular_move_lifecycle(monkeypatch):
    _install_minimal_pyqt(monkeypatch)
    jellyfin = types.ModuleType("dragontools.gui.jellyfin_refresh_dispatch")
    jellyfin.dispatch_after_move = lambda *_a, **_k: None
    monkeypatch.setitem(sys.modules, "dragontools.gui.jellyfin_refresh_dispatch", jellyfin)
    sys.modules.pop("dragontools.gui.move_regular_lifecycle", None)
    return importlib.import_module("dragontools.gui.move_regular_lifecycle")


def test_regular_move_start_failure_is_terminal_error_and_releases_claim(monkeypatch):
    module = _import_regular_move_lifecycle(monkeypatch)

    state = SimpleNamespace(
        start_reserved=True,
        move_thread=None,
        incremental_move_active=False,
        planned_targets={},
        restored_move_context={},
        retired_move_threads=[],
        sidecars_for_move=lambda: {},
    )
    ui = SimpleNamespace(
        file_bar=_Bar(), eta_lbl=_Label(), progress_bar=_Bar(), total_lbl=_Label(),
        shut_cb=_Check(False), abort_btn=_Button(), pause_btn=_Button(), curlog_btn=_Button(),
    )
    starts = []
    queue_edit = []
    finalizations = []

    lifecycle = module.RegularMoveLifecycle(
        state=state,
        ui=ui,
        log=lambda *_a, **_k: None,
        get_target_paths=lambda: {},
        finalize_run=lambda *args, **kwargs: finalizations.append((args, kwargs)),
        set_start_enabled=starts.append,
        set_queue_edit=queue_edit.append,
        refresh_queue=lambda: None,
        worker_factory=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("cannot create MoveThread")),
        on_move_req=lambda *_a: None,
    )
    finished = SimpleNamespace(log_file_path="convert.log")

    assert lifecycle.start(["out.mkv"], finished) is False
    assert state.start_reserved is False
    assert state.move_thread is None
    assert starts[-1] is True
    assert queue_edit[-1] is True
    assert ui.abort_btn.enabled is False
    assert ui.pause_btn.enabled is False
    assert finalizations and finalizations[-1][1]["move_errors"] == 1


def test_regular_move_terminal_releases_claim_even_when_finalizer_raises(monkeypatch):
    module = _import_regular_move_lifecycle(monkeypatch)

    move_thread = SimpleNamespace(
        abort_requested=False,
        _move_report_log=[],
        ok_count=0,
        error_count=0,
        log_file_path=None,
        user_declined_shutdown=False,
    )
    state = SimpleNamespace(
        start_reserved=True,
        move_thread=move_thread,
        restored_move_context={},
        retired_move_threads=[],
    )
    ui = SimpleNamespace(
        abort_btn=_Button(), eta_lbl=_Label(), curlog_btn=_Button(), pause_btn=_Button(),
    )
    starts = []
    queue_edit = []
    lifecycle = module.RegularMoveLifecycle(
        state=state,
        ui=ui,
        log=lambda *_a, **_k: None,
        get_target_paths=lambda: {},
        finalize_run=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("dialog failed")),
        set_start_enabled=starts.append,
        set_queue_edit=queue_edit.append,
        refresh_queue=lambda: None,
        worker_factory=lambda *_a, **_k: None,
        on_move_req=lambda *_a: None,
    )

    lifecycle._finish(move_thread, finished_thread=SimpleNamespace(log_file_path=None), moved=False, shutdown=False)

    assert state.start_reserved is False
    assert state.move_thread is None
    assert move_thread in state.retired_move_threads
    assert starts[-1] is True
    assert queue_edit[-1] is True
    assert ui.pause_btn.enabled is False


def test_move_only_claims_start_before_handing_off_to_move(monkeypatch, tmp_path):
    _install_minimal_pyqt(monkeypatch)
    preflight_dialog = types.ModuleType("dragontools.gui.preflight_dialog")
    preflight_dialog.PreFlightDialog = object
    monkeypatch.setitem(sys.modules, "dragontools.gui.preflight_dialog", preflight_dialog)
    sys.modules.pop("dragontools.gui.conversion_start_coordinator", None)
    module = importlib.import_module("dragontools.gui.conversion_start_coordinator")

    video = tmp_path / "film.mkv"
    video.write_bytes(b"x")
    path = str(video)
    state = SimpleNamespace(
        start_reserved=False,
        planned_targets={path: {"kind": "film"}},
        sidecar_outputs_by_video={},
        restored_move_context={"target_paths": {}},
        fertig=set(),
    )
    observed_claims = []
    preflight = SimpleNamespace(
        start_move=lambda _files, _thread: observed_claims.append(state.start_reserved) or True,
        save_report=lambda *_a, **_k: None,
    )
    ui = SimpleNamespace(
        file_list=SimpleNamespace(get_paths=lambda: [path]),
        abort_btn=_Button(), pause_btn=_Button(),
    )
    coordinator = module.ConversionStartCoordinator(
        state=state,
        ui=ui,
        log=lambda *_a, **_k: None,
        collect_encoder_options=lambda: {},
        get_target_paths=lambda: {},
        refresh_queue=lambda: None,
        set_start_enabled=lambda _v: None,
        set_queue_edit=lambda _v: None,
        preflight=preflight,
        worker_factory=SimpleNamespace(),
        lifecycle=SimpleNamespace(active_worker=lambda: None),
        progress_presenter=SimpleNamespace(reset=lambda _n: None),
        qt_parent=None,
    )

    coordinator.start_move_only()

    assert observed_claims == [True]
    assert state.start_reserved is True


def test_start_convert_connect_failure_clears_stale_worker_reference(monkeypatch):
    _install_minimal_pyqt(monkeypatch)
    sys.modules.pop("dragontools.gui.conversion_start_coordinator", None)
    module = importlib.import_module("dragontools.gui.conversion_start_coordinator")

    worker = object()
    state = SimpleNamespace(thread=None, start_reserved=False)
    ui = SimpleNamespace(
        file_list=SimpleNamespace(get_paths=lambda: ["film.mkv"]),
        pause_btn=_Button(), progress_bar=_Bar(), over_cb=_Check(False),
    )

    class _Lifecycle:
        def active_worker(self):
            return None

        def connect_worker_signals(self, *_args, **_kwargs):
            raise RuntimeError("signal object already deleted")

    monkeypatch.setattr(module, "parallel_jobs_for_encoder", lambda *_a, **_k: 1)
    monkeypatch.setattr(module.ConversionStartCoordinator, "confirm_disk_space", lambda *_a, **_k: True)
    coordinator = module.ConversionStartCoordinator(
        state=state, ui=ui, log=lambda *_a, **_k: None,
        collect_encoder_options=lambda: {"encoder": "cpu"}, get_target_paths=lambda: {},
        refresh_queue=lambda: None, set_start_enabled=lambda _v: None, set_queue_edit=lambda _v: None,
        preflight=SimpleNamespace(run_if_needed=lambda _files: True),
        worker_factory=SimpleNamespace(create_converter=lambda *_a, **_k: worker),
        lifecycle=_Lifecycle(),
        progress_presenter=SimpleNamespace(reset=lambda _n: None, on_total_progress=lambda _p: None),
        qt_parent=SimpleNamespace(settings=object()),
    )

    coordinator.start_convert()

    assert state.thread is None
    assert state.start_reserved is False


def test_move_only_exception_after_ui_lock_restores_controls(monkeypatch, tmp_path):
    _install_minimal_pyqt(monkeypatch)
    preflight_dialog = types.ModuleType("dragontools.gui.preflight_dialog")
    preflight_dialog.PreFlightDialog = object
    monkeypatch.setitem(sys.modules, "dragontools.gui.preflight_dialog", preflight_dialog)
    sys.modules.pop("dragontools.gui.conversion_start_coordinator", None)
    module = importlib.import_module("dragontools.gui.conversion_start_coordinator")

    path = str(tmp_path / "film.mkv")
    Path(path).write_bytes(b"x")
    state = SimpleNamespace(
        start_reserved=False,
        planned_targets={path: {"kind": "film"}},
        sidecar_outputs_by_video={}, restored_move_context={"target_paths": {}}, fertig=set(),
    )
    start_enabled = []
    queue_enabled = []
    ui = SimpleNamespace(file_list=SimpleNamespace(get_paths=lambda: [path]), abort_btn=_Button(), pause_btn=_Button())
    coordinator = module.ConversionStartCoordinator(
        state=state, ui=ui, log=lambda *_a, **_k: None,
        collect_encoder_options=lambda: {}, get_target_paths=lambda: {}, refresh_queue=lambda: None,
        set_start_enabled=start_enabled.append, set_queue_edit=queue_enabled.append,
        preflight=SimpleNamespace(
            start_move=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("handoff failed")),
            save_report=lambda *_a, **_k: None,
        ),
        worker_factory=SimpleNamespace(), lifecycle=SimpleNamespace(active_worker=lambda: None),
        progress_presenter=SimpleNamespace(reset=lambda _n: None), qt_parent=None,
    )

    coordinator.start_move_only()

    assert state.start_reserved is False
    assert start_enabled[-1] is True
    assert queue_enabled[-1] is True
    assert ui.abort_btn.enabled is False
    assert ui.pause_btn.enabled is False


def test_runtime_ui_treats_destroyed_move_thread_as_inactive(monkeypatch):
    _install_minimal_pyqt(monkeypatch)
    sys.modules.pop("dragontools.gui.convert_widget_runtime_ui", None)
    module = importlib.import_module("dragontools.gui.convert_widget_runtime_ui")

    class _Destroyed:
        def isRunning(self):
            raise RuntimeError("wrapped C/C++ object has been deleted")

    runtime = module.ConvertWidgetRuntimeUI(
        parent_widget=SimpleNamespace(), state=SimpleNamespace(move_thread=_Destroyed()),
        ui=SimpleNamespace(), log=lambda *_a, **_k: None, refresh_queue=lambda: None,
    )

    assert runtime.is_move_active() is False


def test_diagnostics_destroyed_worker_does_not_raise():
    from dragontools.gui.conversion_diagnostics import ConversionDiagnosticsService

    class _Destroyed:
        abort_requested = False
        abort_type = None
        _paused = False

        def isRunning(self):
            raise RuntimeError("wrapped C/C++ object has been deleted")

    service = ConversionDiagnosticsService(state=SimpleNamespace(current_log_path=None, total_files=0))
    text = service.report(_Destroyed())

    assert "Diagnose konnte nicht erstellt werden" in text


def test_finalizer_notification_failure_cannot_skip_terminal_cleanup():
    from dragontools.gui.conversion_run_finalizer import ConversionRunFinalizerMixin

    class _Harness(ConversionRunFinalizerMixin):
        pass

    class _BrokenNotifications:
        def on_run_finished(self, *_a, **_k):
            raise RuntimeError("notification backend failed")

        def on_internal_error(self, *_a, **_k):
            raise RuntimeError("notification backend failed again")

    state = SimpleNamespace(
        summary_written=False, finalization_in_progress=False, move_report_log=[], move_ok_count=0,
        move_error_count=0, run_results={}, job_journal=None, job_journal_current_path=None,
        job_journal_current_paths=set(), watch_intake_blocked=False,
    )
    h = _Harness()
    h._state = state
    h._ui = SimpleNamespace(shut_cb=_Check(False))
    h._notifications = _BrokenNotifications()
    h._log = lambda *_a, **_k: None
    h._parent_widget = None
    h._requeue_files = None
    h.log_run_summary = lambda *_a, **_k: None
    h._show_replacement_reminders = lambda: None
    h._show_run_summary_dialog = lambda *_a, **_k: []
    cleared = []
    h._clear = lambda: cleared.append(True)
    h._confirm_shutdown = lambda: None

    h.finalize_run(SimpleNamespace(abort_requested=False), move_log=[])

    assert cleared == [True]
    assert state.summary_written is True


def test_post_journal_pre_start_failure_rolls_back_active_journal(monkeypatch):
    from dragontools.gui.conversion_worker_lifecycle import ConversionWorkerLifecycle

    class _Journal:
        def __init__(self):
            self.statuses = []

        def finish_run(self, *, status):
            self.statuses.append(status)

    journal = _Journal()
    state = SimpleNamespace(
        current_log_path=None,
        job_journal=None,
        job_journal_current_path="pending",
        job_journal_current_paths={"pending"},
        thread=None,
        move_thread=None,
        retired_move_threads=[],
    )
    ui = SimpleNamespace(
        abort_btn=_Button(), progress_bar=_Bar(), curlog_btn=_Button(), pause_btn=_Button()
    )
    starts = []

    class _Worker:
        log_file_path = "run.log"

        def start(self):
            raise AssertionError("worker.start() must not be reached")

    lifecycle = ConversionWorkerLifecycle(
        state=state,
        ui=ui,
        log=lambda *_a, **_k: None,
        set_start_enabled=starts.append,
        refresh_queue=lambda: None,
        result_service=SimpleNamespace(),
        progress_presenter=SimpleNamespace(
            refresh_queue_after_file_progress=lambda _pct: (_ for _ in ()).throw(
                RuntimeError("progress widget already deleted")
            )
        ),
        default_codec="h265",
        collect_encoder_options=lambda: {},
    )

    def _journal_start(*_args, **_kwargs):
        state.job_journal = journal
        return True

    monkeypatch.setattr(lifecycle, "start_job_journal", _journal_start)

    result = lifecycle.start_worker_ui_state(
        _Worker(), "start", mode="convert", files=["a.mkv"]
    )

    assert result is False
    assert journal.statuses == ["start_failed"]
    assert state.job_journal is None
    assert state.current_log_path is None
    assert starts[-1] is True
    assert ui.abort_btn.enabled is False


def test_finalizer_logger_backend_failure_cannot_block_terminal_cleanup():
    from dragontools.gui.conversion_run_finalizer import ConversionRunFinalizerMixin

    class _Journal:
        def __init__(self):
            self.status = None

        def finish_run(self, *, status):
            self.status = status

    class _Harness(ConversionRunFinalizerMixin):
        pass

    journal = _Journal()
    state = SimpleNamespace(
        summary_written=False,
        finalization_in_progress=False,
        move_report_log=[],
        move_ok_count=0,
        move_error_count=0,
        run_results={},
        job_journal=journal,
        job_journal_current_path="a",
        job_journal_current_paths={"a"},
        watch_intake_blocked=False,
    )
    h = _Harness()
    h._state = state
    h._ui = SimpleNamespace(shut_cb=_Check(False))
    h._log = lambda *_a, **_k: (_ for _ in ()).throw(OSError("log backend unavailable"))
    h._parent_widget = None
    h._notifications = None
    h._requeue_files = None
    cleared = []
    h._clear = lambda: cleared.append(True)
    h._confirm_shutdown = lambda: None
    h.log_run_summary = lambda *_a, **_k: (_ for _ in ()).throw(OSError("summary log failed"))
    h._show_replacement_reminders = lambda: None
    h._show_run_summary_dialog = lambda *_a, **_k: []

    h.finalize_run(SimpleNamespace(abort_requested=False), move_log=[])

    assert cleared == [True]
    assert journal.status == "completed"
    assert state.job_journal is None
    assert state.summary_written is True
    assert state.finalization_in_progress is False
