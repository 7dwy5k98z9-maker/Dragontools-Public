from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import pytest


class Signal:
    def __init__(self):
        self.slots = []

    def connect(self, callback):
        self.slots.append(callback)

    def emit(self, *args):
        for callback in self.slots:
            callback(*args)


def queue_worker(files, overrides):
    from dragontools.worker.converter_queue_state import ConverterQueueState
    from dragontools.worker.converter_thread import ConverterThread
    queue = ConverterQueueState(files)
    worker = SimpleNamespace(
        _queue=queue, _files_lock=queue.lock,
        _job_state=SimpleNamespace(file_overrides=overrides),
        _session_state=SimpleNamespace(all_input_files=list(files)),
        log=lambda *_: None,
    )
    worker.add_file = lambda path: ConverterThread.add_file(worker, path)
    return worker


@pytest.mark.parametrize("state", ["waiting", "current", "done"])
def test_rejected_live_add_preserves_existing_override(state):
    from dragontools.worker.converter_thread import ConverterThread
    path = r"C:\Videos\Film.mkv"
    original = {"encoder_profile": {"encoder_options": {"preset": "slow"}}}
    worker = queue_worker([path], {path: original})
    if state == "current":
        worker._queue.next_file(0)
    elif state == "done":
        worker._queue.complete_current(path)
    assert ConverterThread.add_file_with_override(worker, path, {"sdr_hdr": True}) is False
    assert worker._job_state.file_overrides[path] == original
    assert worker._session_state.all_input_files == [path]


def test_live_add_copies_profile_before_file_is_visible():
    from dragontools.worker.converter_thread import ConverterThread
    path = r"C:\Videos\New.mkv"
    incoming = {"encoder_profile": {"encoder_options": {"preset": "slow"}}}
    worker = queue_worker([], {})
    assert ConverterThread.add_file_with_override(worker, path, incoming)
    assert worker._queue.next_file(0)[0] == path
    incoming["encoder_profile"]["encoder_options"]["preset"] = "fast"
    assert worker._job_state.file_overrides[path]["encoder_profile"]["encoder_options"]["preset"] == "slow"


def test_override_update_by_windows_alias_replaces_effective_profile():
    from dragontools.worker.converter_thread import ConverterThread
    from dragontools.worker.worker_contracts import file_override_for_path
    path = r"C:\Videos\Film.mkv"
    worker = queue_worker([path], {path: {"audio": {"mode": "copy"}}})
    incoming = {"audio": {"mode": "aac"}}
    assert ConverterThread.update_override(worker, "c:/videos/FILM.mkv", incoming)
    incoming["audio"]["mode"] = "changed"
    assert file_override_for_path(worker._job_state.file_overrides, path)["audio"]["mode"] == "aac"
    assert len(worker._job_state.file_overrides) == 1


@pytest.mark.parametrize("field", ["encoder_options", "file_overrides", "subtitle_rules"])
def test_worker_owned_config_has_no_nested_sharing(field):
    from dragontools.worker.converter_config import ConverterConfig
    from dragontools.worker.converter_thread_state import ConverterJobState
    config = ConverterConfig("h265", 23, "medium", "original", False)
    setattr(config, field, {"nested": {"value": [1]}})
    first, second = ConverterJobState.from_config(config), ConverterJobState.from_config(config)
    getattr(first, field)["nested"]["value"].append(2)
    assert getattr(second, field)["nested"]["value"] == [1]
    assert getattr(config, field)["nested"]["value"] == [1]


@pytest.mark.parametrize("signal,args", [
    ("log_line", ("late log",)),
    ("file_progress", ("a.mkv", 40, 10)),
    ("file_result", ("a.mkv", "out.mkv", "✅")),
    ("encode_stage_complete", ("a.mkv", "out.mkv")),
    ("progress", (40,)), ("finished", ()),
])
def test_old_worker_callbacks_cannot_mutate_new_run(signal, args):
    from dragontools.gui.conversion_worker_lifecycle import ConversionWorkerLifecycle
    worker = SimpleNamespace(**{key: Signal() for key in (
        "log_line", "file_progress", "file_result", "encode_stage_complete", "progress", "finished"
    )})
    events = []
    callback = lambda *values: events.append(values)
    state = SimpleNamespace(thread=worker)
    lifecycle = ConversionWorkerLifecycle(
        state=state, ui=SimpleNamespace(), log=callback,
        set_start_enabled=callback, refresh_queue=callback,
        result_service=SimpleNamespace(on_file_progress=callback, on_file_result=callback, on_finished=callback),
        progress_presenter=SimpleNamespace(on_file_result_cleanup=callback,
            on_encode_stage_complete=callback, clear_active_progress_display=callback),
        default_codec="h265", collect_encoder_options=lambda: {},
    )
    lifecycle.connect_worker_signals(worker, callback)
    getattr(worker, signal).emit(*args)
    assert events
    events.clear()
    state.thread = object()
    getattr(worker, signal).emit(*args)
    assert events == []


def result_service(tmp_path, *, broken_log=False):
    from dragontools.worker.worker_result_service import WorkerConversionResultService
    output = tmp_path / "output.mkv"
    output.write_bytes(b"valid output")
    runtime = SimpleNamespace(total_before=0, total_after=0, erfolgreich=0, fehlgeschlagen=0)
    results = []
    def log(*args):
        if broken_log:
            raise OSError("logger unavailable")
    service = WorkerConversionResultService(
        logger=SimpleNamespace(file_done=lambda **_: None), runtime_state=runtime,
        overwrite_original=False, event_emit=lambda *_: None,
        file_progress_emit=lambda *_: None, file_result_emit=lambda *args: results.append(args),
        log=log, failure_details={},
    )
    ctx = SimpleNamespace(input_path="in.mkv", output_path=str(output),
        final_output_path=str(output), size_before=30, start_ts=0)
    return service, runtime, results, ctx


@pytest.mark.parametrize("method", ["finalize_success", "finalize_cleanup_pending", "finalize_blocked", "fail", "fail_unhandled"])
def test_duplicate_finalizers_count_file_once(tmp_path, method):
    service, runtime, results, ctx = result_service(tmp_path)
    args = (ctx, "failure") if method == "fail" else ((ctx.input_path,) if method == "fail_unhandled" else (ctx,))
    getattr(service, method)(*args)
    getattr(service, method)(*args)
    assert runtime.erfolgreich + runtime.fehlgeschlagen == 1
    assert len(results) == 1
    if method == "finalize_success":
        assert runtime.total_before == 30
        assert runtime.total_after == len(b"valid output")


@pytest.mark.parametrize("method", ["finalize_cleanup_pending", "finalize_blocked", "fail", "fail_unhandled"])
def test_failure_logger_cannot_suppress_terminal_result(tmp_path, method):
    service, runtime, results, ctx = result_service(tmp_path, broken_log=True)
    args = (ctx, "failure") if method == "fail" else ((ctx.input_path,) if method == "fail_unhandled" else (ctx,))
    getattr(service, method)(*args)
    assert runtime.fehlgeschlagen == 1
    assert len(results) == 1


@pytest.mark.parametrize("fault", ["shutdown_log", "dialog_log", "journal_log", "reentrant_clear"])
def test_gui_finalizer_cannot_skip_journal_or_finalize_twice(fault):
    from dragontools.gui.conversion_run_finalizer import ConversionRunFinalizerMixin
    from dragontools.gui.conversion_session_state import ConversionSessionState
    class Harness(ConversionRunFinalizerMixin):
        pass
    state = ConversionSessionState()
    finishes, clears = [], []
    def finish(**kwargs):
        finishes.append(kwargs["status"])
        if fault == "journal_log":
            raise OSError("journal unavailable")
    state.job_journal = SimpleNamespace(finish_run=finish)
    h = Harness()
    h._state = state
    h._ui = SimpleNamespace(shut_cb=SimpleNamespace(isChecked=lambda: fault == "shutdown_log"))
    h._log = lambda *_: (_ for _ in ()).throw(OSError("logger unavailable"))
    h._notifications = None
    h._requeue_files = None
    h._parent_widget = None
    h.log_run_summary = lambda *_: None
    h._show_replacement_reminders = lambda: None
    h._show_run_summary_dialog = lambda *_a, **_k: []
    if fault == "dialog_log":
        h._show_run_summary_dialog = lambda *_a, **_k: (_ for _ in ()).throw(OSError("dialog logger failed"))
    h._confirm_shutdown = lambda: None
    thread = SimpleNamespace(abort_requested=False)
    def clear():
        clears.append(True)
        state.clear_all()
        if fault == "reentrant_clear" and len(clears) == 1:
            h.finalize_run(thread)
    h._clear = clear
    h.finalize_run(thread)
    h.finalize_run(thread)
    assert finishes == ["completed"]
    assert clears == [True]
    assert state.job_journal is None
    assert state.summary_written
    assert not state.finalization_in_progress


@pytest.mark.parametrize("payload,code", [([], 0), (1, 0), ({"streams": [1]}, 0),
    ({"streams": [{"width": 1920, "height": 1080}]}, 1),
    ({"streams": [{"width": -1, "height": 1080}]}, 0)])
def test_optional_resolution_probe_is_nonfatal_and_validated(monkeypatch, payload, code):
    import dragontools.worker.converter_run_loop as module
    monkeypatch.setattr(module.subprocess, "run", lambda *_a, **_k:
        SimpleNamespace(stdout=json.dumps(payload), returncode=code))
    assert module.quick_video_resolution("film.mkv", "ffprobe") is None


@pytest.mark.parametrize("value", [float("inf"), float("nan"), "inf", "1e999"])
def test_nonfinite_eta_is_ignored(value):
    from dragontools.gui.conversion_progress_display import ConversionProgressDisplay
    assert ConversionProgressDisplay.format_eta(value) == ""


@pytest.mark.parametrize("state", ["waiting", "current", "pending"])
def test_queue_logging_happens_after_releasing_queue_lock(state):
    from dragontools.worker.converter_queue_state import ConverterQueueState
    queue = ConverterQueueState(["a.mkv"])
    if state in ("current", "pending"):
        queue.next_file(0)
    if state == "pending":
        queue.pending_remove_files.add("a.mkv")
    lock_available = []
    def log(*_):
        acquired = queue.lock.acquire(blocking=False)
        lock_available.append(acquired)
        if acquired:
            queue.lock.release()
    queue.remove_file("a.mkv", log)
    assert lock_available == [True]


def test_current_ffmpeg_termination_targets_the_validated_process(monkeypatch):
    import dragontools.worker.converter_control as module
    original = SimpleNamespace(args=["ffmpeg.exe"], poll=lambda: None)
    next_process = SimpleNamespace(args=["mkvmerge.exe"], poll=lambda: None)
    state = SimpleNamespace(current_process=original, process_lock=threading.Lock())
    targets = []
    worker = SimpleNamespace(_files_lock=threading.Lock(), _queue=SimpleNamespace(current_file="a.mkv"))
    worker.log = lambda *_: setattr(state, "current_process", next_process)
    monkeypatch.setattr(module, "terminate_process_tree", lambda *_a, **kwargs:
        targets.append(kwargs.get("process", state.current_process)) or True)
    assert module.ConverterControlService(worker, state).terminate_current_ffmpeg("a.mkv")
    assert targets == [original]


@pytest.mark.parametrize("failure_stage", ["commit", "verification_log"])
def test_verified_video_and_sidecar_survive_late_failure(tmp_path, failure_stage):
    from dragontools.worker.workflow_engine import ConversionWorkflowRunner, WorkflowVerifyResult
    from dragontools.worker.workflow_services import WorkflowServices
    from dragontools.worker.workflow_verification_service import WorkflowVerificationService
    from dragontools.worker.cleanup_service import CleanupService
    output, sidecar = tmp_path / "out.mkv", tmp_path / "out.de.srt"
    failures = []
    verified = WorkflowVerifyResult(exists=True, size_ok=True, container_ok=True,
        probe_ok=True, video_ok=True, duration_ok=True)
    class Logger:
        def info(self, *_):
            if failure_stage == "verification_log":
                raise OSError("logger unavailable")
        warn = error = info
    verification = WorkflowVerificationService(output_verifier=SimpleNamespace(verify=lambda *_a, **_k: verified),
        duration_repair_service=None, logger=Logger())
    actual = WorkflowServices.__new__(WorkflowServices)
    actual._verification = verification
    actual._temp_state = SimpleNamespace(burn_sub_tmp=None)
    actual._output_commit = SimpleNamespace()
    actual._cleanup_service = CleanupService(overwrite_original=False, temp_overwrite_dir=lambda p: p / "temp", log=lambda *_: None)
    class Services:
        def analyze(self, ctx):
            ctx.analysis = SimpleNamespace(audio_streams=[])
        def build_plan(self, ctx, override):
            ctx.base_dir, ctx.output_path, ctx.container = tmp_path, str(output), "mkv"
        def process(self, ctx, override):
            output.write_bytes(b"verified video")
            sidecar.write_text("subtitle", encoding="utf-8")
            ctx.sidecar_paths = [str(sidecar)]
        def verify(self, ctx):
            actual.verify(ctx)
        def replace(self, ctx):
            raise OSError("late sidecar commit failed")
        def fail(self, ctx, *args):
            failures.append(ctx)
        def cleanup(self, ctx):
            actual.cleanup(ctx)
    assert not ConversionWorkflowRunner(Services(), replace_original=False).run("source.mkv", {})
    assert len(failures) == 1
    assert output.exists()
    assert sidecar.exists()


@pytest.mark.parametrize("blocked", ["duplicate", "not_running", "abort"])
def test_parallel_rejected_live_add_preserves_existing_profile(blocked):
    from dragontools.worker.parallel_converter_queue import ParallelConverterQueueMixin
    from dragontools.core.path_syntax import path_compare_key
    class Harness(ParallelConverterQueueMixin):
        pass
    h = Harness()
    path = "a.mkv"
    h._running = blocked != "not_running"
    h.abort_requested = blocked == "abort"
    key = path_compare_key(path)
    h._assigned = {key: object()} if blocked == "duplicate" else {}
    h._queue_state = SimpleNamespace(file_keys={key} if blocked == "duplicate" else set())
    original = {"encoder_profile": {"encoder_options": {"preset": "slow"}}}
    h.file_overrides = {path: original}
    assert h.add_file_with_override(path, {"sdr_hdr": True}) is False
    assert h.file_overrides[path] == original


@pytest.mark.parametrize("carrier", ["encoder_profile", "encoder_override"])
def test_optional_runtime_honors_profile_backend_and_its_own_endpoint(monkeypatch, carrier):
    import dragontools.worker.converter_optional_runtime as module
    from dragontools.core.encoder_profile_override import effective_encoder_settings
    profile = {"codec": "h265", "encoder": "cpu", "encoder_options": {
        "sdr_hdr_enabled": True, "sdr_hdr_backend": "comfyui", "comfyui_base_url": "http://127.0.0.1:8288"}}
    override = {carrier: profile}
    job = SimpleNamespace(codec="h265", crf=23, preset="medium", scale_mode="original",
        encoder_options={"sdr_hdr_enabled": False, "sdr_hdr_backend": "ffmpeg"}, file_overrides={"a.mkv": override})
    worker = SimpleNamespace(_job_state=job, log=lambda *_: None)
    tools = SimpleNamespace(ffmpeg="ffmpeg", davinci_resolve="Resolve.exe", hdr10plus_generator="generator")
    monkeypatch.setattr(module, "ffmpeg_has_libplacebo", lambda *_: False)
    monkeypatch.setattr(module, "generator_executable_available", lambda *_: False)
    monkeypatch.setattr(module, "_configure_hdr10plus_generator", lambda *_: None)
    calls = []
    def probe(_worker, _tools, options):
        calls.append(options["comfyui_base_url"])
        options["_comfyui_backend_ready"] = True
        options["_comfyui_model_repository"] = "chosen model"
    monkeypatch.setattr(module, "configure_comfyui_runtime", probe)
    module.configure_optional_runtime_features(worker, tools)
    effective = effective_encoder_settings(default_codec="h265", default_crf=23,
        default_preset="medium", default_scale_mode="original",
        default_encoder_options=job.encoder_options, file_override=override)["encoder_options"]
    assert calls == ["http://127.0.0.1:8288"]
    assert effective["_comfyui_backend_ready"]
    assert effective["_comfyui_model_repository"] == "chosen model"
    assert job.encoder_options["sdr_hdr_backend"] == "ffmpeg"
    assert "_comfyui_backend_ready" not in job.encoder_options


def test_progress_speed_cannot_produce_infinite_eta(monkeypatch):
    import dragontools.worker.converter_progress_parser as module
    values = []
    worker = SimpleNamespace(wait_if_paused=lambda: None, abort_requested=False,
        emit_file_progress=lambda *args: values.append(args))
    proc = SimpleNamespace(stdout=["speed=5e-324x", "out_time_ms=1000000", "progress=end"])
    module.read_progress(worker, proc, "a.mkv", 60000)
    assert values[0][2] is None
    assert values[-1] == ("a.mkv", 100, 0.0)


def test_finalizer_reservation_blocks_reentrant_start():
    from dragontools.gui.conversion_start_coordinator import ConversionStartCoordinator
    h = SimpleNamespace(_state=SimpleNamespace(start_reserved=False, finalization_in_progress=True),
        _log=lambda *_: None, _lifecycle=SimpleNamespace(active_worker=lambda: None))
    assert ConversionStartCoordinator._claim_start(h) is False


@pytest.mark.parametrize("blocked", ["current", "done"])
def test_override_rejection_logs_after_releasing_queue_lock(blocked):
    from dragontools.worker.converter_thread import ConverterThread
    worker = queue_worker(["a.mkv"], {})
    if blocked == "current":
        worker._queue.next_file(0)
    else:
        worker._queue.complete_current("a.mkv")
    available = []
    def log(*_):
        ok = worker._files_lock.acquire(blocking=False)
        available.append(ok)
        if ok:
            worker._files_lock.release()
    worker.log = log
    assert not ConverterThread.update_override(worker, "a.mkv", {})
    assert available == [True]


def test_terminal_statistics_follow_one_error_upgrade(tmp_path):
    service, runtime, results, ctx = result_service(tmp_path)
    service.finalize_success(ctx)
    service.fail(ctx, "late failure")
    service.fail(ctx, "duplicate failure")
    service.finalize_success(ctx)
    assert [row[-1] for row in results] == ["✅", "❌"]
    assert (runtime.erfolgreich, runtime.fehlgeschlagen) == (0, 1)


def test_async_pending_completion_does_not_count_success_twice(tmp_path):
    service, runtime, results, ctx = result_service(tmp_path)
    service.finalize_success_pending_postprocess(ctx)
    service.emit_file_result(ctx.input_path, ctx.output_path, "✅")
    service.finalize_success(ctx)
    assert runtime.erfolgreich == 1
    assert runtime.total_before == 30
    assert [row[-1] for row in results] == ["🧩", "✅"]


@pytest.mark.parametrize("boundary", ["event", "progress"])
def test_diagnostic_callback_failure_cannot_suppress_success_result(tmp_path, boundary):
    service, runtime, results, ctx = result_service(tmp_path)
    broken = lambda *_: (_ for _ in ()).throw(RuntimeError("observer failed"))
    if boundary == "event":
        service._event_emit = broken
    else:
        service._file_progress_emit = broken
    service.finalize_success(ctx)
    assert runtime.erfolgreich == 1
    assert results == [(ctx.input_path, ctx.output_path, "✅")]


def test_duplicate_success_after_output_move_remains_idempotent(tmp_path):
    from pathlib import Path
    service, runtime, results, ctx = result_service(tmp_path)
    service.finalize_success(ctx)
    Path(ctx.output_path).rename(tmp_path / "moved.mkv")
    service.finalize_success(ctx)
    assert runtime.erfolgreich == 1
    assert len(results) == 1


def test_finished_queue_cannot_accept_an_unprocessed_live_file():
    from dragontools.worker.converter_queue_state import ConverterQueueState
    queue = ConverterQueueState(["a.mkv"])
    queue.next_file(0)
    queue.complete_current("a.mkv")
    assert queue.next_file(1) is None
    assert queue.add_file("late.mkv", lambda *_: None) is False
    assert queue.files == []


def test_queue_log_failure_does_not_undo_accepted_live_add():
    from dragontools.worker.converter_thread import ConverterThread
    from dragontools.core.path_syntax import path_compare_key
    worker = queue_worker([], {})
    worker.log = lambda *_: (_ for _ in ()).throw(OSError("logger unavailable"))
    assert ConverterThread.add_file_with_override(worker, "a.mkv", {"sdr_hdr": True})
    assert worker._session_state.all_input_files == ["a.mkv"]
    assert path_compare_key(worker._queue.next_file(0)[0]) == path_compare_key("a.mkv")


def test_optional_backend_failure_does_not_abort_file_runtime(monkeypatch):
    import dragontools.worker.converter_optional_runtime as module
    override = {"encoder_profile": {"codec": "h265", "encoder_options": {
        "sdr_hdr_enabled": True, "sdr_hdr_backend": "comfyui"}}}
    worker = SimpleNamespace(_job_state=SimpleNamespace(encoder_options={}), log=lambda *_: None)
    monkeypatch.setattr(module, "configure_comfyui_runtime",
        lambda *_: (_ for _ in ()).throw(RuntimeError("backend unavailable")))
    module.configure_optional_file_runtime(worker, SimpleNamespace(), override)
    assert override["encoder_profile"]["encoder_options"]["_comfyui_backend_ready"] is False


def test_parallel_live_add_survives_logging_failure():
    from dragontools.worker.parallel_converter_queue import ParallelConverterQueueMixin
    class Harness(ParallelConverterQueueMixin):
        pass
    h = Harness()
    h._running, h.abort_requested, h._paused = True, False, True
    h._assigned, h.file_overrides = {}, {}
    h._queue_state = SimpleNamespace(file_keys=set())
    h._active_workers, h.files, h._pending_files = [], [], []
    h.parallel_jobs = 1
    h._rebuild_display_positions = h._emit_aggregate_progress = lambda: None
    h._logger = SimpleNamespace(info=lambda *_: (_ for _ in ()).throw(OSError("logger unavailable")))
    assert h.add_file_with_override("a.mkv", {"sdr_hdr": True})
    assert h._pending_files == ["a.mkv"]
    assert h.file_overrides["a.mkv"] == {"sdr_hdr": True}


@pytest.mark.parametrize("field", ["encoder_options", "file_overrides", "subtitle_rules"])
def test_parallel_config_has_no_nested_sharing(monkeypatch, field):
    import dragontools.worker.parallel_converter_thread as module
    from dragontools.worker.converter_config import ConverterConfig
    config = ConverterConfig("h265", 23, "medium", "original", False)
    setattr(config, field, {"nested": {"value": [1]}})
    monkeypatch.setattr(module, "create_worker_logger", lambda **_: SimpleNamespace(log_file=None))
    monkeypatch.setattr(module.ParallelConverterThread, "_initialize_gpu_log_context", lambda *_: None)
    worker = module.ParallelConverterThread([], config, parallel_jobs=1)
    getattr(config, field)["nested"]["value"].append(2)
    assert getattr(worker, field)["nested"]["value"] == [1]


def test_real_qt_queued_signals_from_old_worker_are_ignored():
    import subprocess
    import sys
    source = '''
import threading
from types import SimpleNamespace
from PyQt6.QtCore import QObject, QCoreApplication, pyqtSignal
from dragontools.gui.conversion_worker_lifecycle import ConversionWorkerLifecycle
class Worker(QObject):
    log_line = pyqtSignal(str)
    file_progress = pyqtSignal(str, int, object)
    file_result = pyqtSignal(str, str, str)
    encode_stage_complete = pyqtSignal(str, str)
    progress = pyqtSignal(int)
    finished = pyqtSignal()
app = QCoreApplication([])
worker = Worker()
events = []
callback = lambda *args: events.append(threading.get_ident())
main = threading.get_ident()
state = SimpleNamespace(thread=worker)
lifecycle = ConversionWorkerLifecycle(state=state, ui=None, log=callback,
    set_start_enabled=callback, refresh_queue=callback,
    result_service=SimpleNamespace(on_file_progress=callback, on_file_result=callback, on_finished=callback),
    progress_presenter=SimpleNamespace(on_file_result_cleanup=callback,
        on_encode_stage_complete=callback, clear_active_progress_display=callback),
    default_codec="h265", collect_encoder_options=lambda: {})
lifecycle.connect_worker_signals(worker, callback)
def emit():
    worker.file_progress.emit("a.mkv", 50, 2)
    worker.file_result.emit("a.mkv", "out.mkv", "ok")
    worker.finished.emit()
thread = threading.Thread(target=emit)
thread.start()
thread.join()
assert not events, "Signals must be queued to the GUI thread"
state.thread = object()
app.processEvents()
assert not events, "Old queued callbacks must not touch the new run"
state.thread = worker
thread = threading.Thread(target=emit)
thread.start()
thread.join()
app.processEvents()
assert events and all(value == main for value in events)
'''
    completed = subprocess.run([sys.executable, "-B", "-c", source], capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=15)
    assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.mark.parametrize("kind", ["completed", "internal_error"])
def test_gui_finalizer_preserves_both_notification_hooks(kind):
    from dragontools.gui.conversion_run_finalizer import ConversionRunFinalizerMixin
    from dragontools.gui.conversion_session_state import ConversionSessionState
    class Harness(ConversionRunFinalizerMixin):
        pass
    h = Harness()
    h._state = ConversionSessionState()
    if kind == "internal_error":
        h._state.move_ok_count = "malformed legacy count"
    h._ui = SimpleNamespace(shut_cb=SimpleNamespace(isChecked=lambda: False))
    h._log = lambda *_: None
    h.log_run_summary = lambda *_: None
    h._show_replacement_reminders = lambda: None
    h._show_run_summary_dialog = lambda *_a, **_k: []
    h._build_run_summary = lambda *_a, **_k: {"ok": 1, "errors": 0}
    h._clear = h._state.clear_all
    h._requeue_files = None
    calls = []
    h._notifications = SimpleNamespace(
        on_run_finished=lambda summary, **kwargs: calls.append(("completed", summary, kwargs)),
        on_internal_error=lambda *args: calls.append(("internal_error", *args)),
    )
    h.finalize_run(SimpleNamespace(abort_requested=False))
    h.finalize_run(SimpleNamespace(abort_requested=False))
    assert len(calls) == 1 and calls[0][0] == kind
    if kind == "completed":
        assert calls[0][1:] == ({"ok": 1, "errors": 0}, {"aborted": False})
    assert h._state.summary_written
    assert not h._state.finalization_in_progress


def test_converter_logging_failure_does_not_abort_worker():
    from dragontools.worker.converter_thread import ConverterThread
    events = []
    worker = SimpleNamespace(worker_event=SimpleNamespace(emit=events.append),
        _logger=SimpleNamespace(info=lambda *_: (_ for _ in ()).throw(OSError("logger unavailable"))))
    ConverterThread.log(worker, "queue processing continues")
    assert len(events) == 1


@pytest.mark.parametrize("enabled", [True, "true"])
def test_live_direct_sdr_hdr_gets_backend_capabilities_before_planning(monkeypatch, enabled):
    import dragontools.worker.converter_optional_runtime as runtime
    from dragontools.worker.converter_file_executor import ConverterFileExecutor
    from dragontools.core.encoder_profile_override import effective_encoder_settings
    from dragontools.core.file_override_normalization import normalize_override_dict
    path = "live.mkv"
    job = SimpleNamespace(codec="h265", crf=23, preset="medium", scale_mode="original",
        encoder_options={"sdr_hdr_enabled": False, "sdr_hdr_backend": "comfyui"},
        file_overrides={path: {"sdr_hdr": enabled}})
    planned_options, probes = [], []
    def probe(_worker, _tools, options):
        probes.append(True)
        options["_comfyui_backend_ready"] = True
    monkeypatch.setattr(runtime, "configure_comfyui_runtime", probe)
    monkeypatch.setattr(ConverterFileExecutor, "_check_source_visual_quality", lambda *_: True)
    def run(_path, override):
        # Follow the canonical normalization boundary into actual plan options.
        planned_options.append(effective_encoder_settings(default_codec="h265", default_crf=23,
            default_preset="medium", default_scale_mode="original",
            default_encoder_options=job.encoder_options,
            file_override=normalize_override_dict(override))["encoder_options"])
        return True
    worker = SimpleNamespace(_job_state=job,
        _services=SimpleNamespace(tools=SimpleNamespace(), workflow_runner=SimpleNamespace(run=run)),
        emit_file_result=lambda *_: None, emit_file_progress=lambda *_: None, log=lambda *_: None)
    assert ConverterFileExecutor(worker).execute(path)
    assert probes == [True]
    assert planned_options[0]["sdr_hdr_enabled"] is True
    assert planned_options[0]["_comfyui_backend_ready"] is True
    assert job.encoder_options == {"sdr_hdr_enabled": False, "sdr_hdr_backend": "comfyui"}


def test_readiness_facts_cannot_override_encoder_or_feature_policy():
    from dragontools.core.encoder_profile_override import effective_encoder_settings
    from dragontools.core.file_override_normalization import normalize_override_dict
    override = {"_encoder_runtime_capabilities": {
        "encoder": "nvenc", "sdr_hdr_enabled": True, "_comfyui_backend_ready": True}}
    for candidate in (override, normalize_override_dict(override)):
        options = effective_encoder_settings(default_codec="h265", default_crf=23,
            default_preset="medium", default_scale_mode="original",
            default_encoder_options={"encoder": "cpu", "sdr_hdr_enabled": False},
            file_override=candidate)["encoder_options"]
        assert options["encoder"] == "cpu"
        assert options["sdr_hdr_enabled"] is False
        assert options["_comfyui_backend_ready"] is True
