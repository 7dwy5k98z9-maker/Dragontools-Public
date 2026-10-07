"""Ownership, cancellation and late-callback regressions for review 16."""
from dataclasses import replace
import os
from types import SimpleNamespace

import pytest

from dragontools.tests.test_parallel_converter_thread import (
    FakeWorker, _install_parallel_fakes, _thread,
)


@pytest.mark.parametrize("error", [RuntimeError("state unavailable"), ValueError("bad state")])
def test_unknown_worker_state_blocks_shutdown(error):
    from dragontools.gui.application_shutdown import shutdown_workers
    calls = []
    def state():
        raise error
    worker = SimpleNamespace(isRunning=state, request_abort=lambda mode: calls.append(mode))
    result = shutdown_workers([worker], timeout_ms=0)
    assert not result.ok
    assert result.requested == 1
    assert calls == ["sofort"]


@pytest.mark.parametrize("generator", [False, True])
def test_failed_worker_discovery_blocks_shutdown(generator):
    from dragontools.gui.application_shutdown import shutdown_loaded_widgets
    def broken():
        raise RuntimeError("provider unavailable")
    def broken_generator():
        yield SimpleNamespace(isRunning=lambda: False)
        broken()
    owner = SimpleNamespace(iter_shutdown_workers=broken_generator if generator else broken)
    result = shutdown_loaded_widgets([owner], timeout_ms=0)
    assert not result.ok
    assert result.still_running


def test_internal_abort_typeerror_does_not_invoke_abort_twice():
    from dragontools.gui.application_shutdown import shutdown_workers
    calls = []
    def abort(mode="sofort"):
        calls.append(mode)
        raise TypeError("error inside abort implementation")
    worker = SimpleNamespace(isRunning=lambda: True, request_abort=abort)
    assert not shutdown_workers([worker], timeout_ms=0).ok
    assert calls == ["sofort"]


def test_zero_argument_abort_and_deleted_native_wrapper_are_supported(qapp):
    from PyQt6.QtCore import QThread
    from PyQt6 import sip
    from dragontools.gui.application_shutdown import shutdown_workers
    state = [True]
    def abort():
        state[0] = False
    worker = SimpleNamespace(isRunning=lambda: state[0], request_abort=abort)
    dead = QThread()
    sip.delete(dead)
    assert shutdown_workers([worker, dead], timeout_ms=0).ok


@pytest.mark.parametrize("accepted", [True, False])
def test_shutdown_logging_cannot_change_os_result(monkeypatch, accepted):
    from dragontools.core import system_shutdown as module
    from dragontools.core import windows_restart_policy as policy
    monkeypatch.setattr(policy, "_USER_SHUTDOWN_ALLOWED_UNTIL", 0.0)
    calls = []
    def run(*args, **kwargs):
        calls.append(args)
        if not accepted:
            raise OSError("OS rejected shutdown")
    monkeypatch.setattr(module.subprocess, "run", run)
    def broken_log(*args):
        raise RuntimeError("display unavailable")
    assert module.schedule_system_shutdown(log=broken_log) is accepted
    assert len(calls) == 1


@pytest.mark.parametrize("delay", ["bad", float("inf"), True, -1])
def test_invalid_shutdown_delay_never_calls_os(monkeypatch, delay):
    from dragontools.core import system_shutdown as module
    calls = []
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **kw: calls.append(a))
    assert module.schedule_system_shutdown(delay_seconds=delay) is False
    assert calls == []


def test_shutdown_permission_covers_requested_delay(monkeypatch):
    from dragontools.core import system_shutdown as module
    from dragontools.core import windows_restart_policy as policy
    stamp = [100.0]
    monkeypatch.setattr(policy.time, "monotonic", lambda: stamp[0])
    monkeypatch.setattr(policy, "_USER_SHUTDOWN_ALLOWED_UNTIL", 0.0)
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **kw: None)
    assert module.schedule_system_shutdown(delay_seconds=600)
    stamp[0] = 701.0
    assert policy.user_initiated_shutdown_allowed()


def test_cleared_shutdown_permission_is_not_active_at_clock_zero(monkeypatch):
    from dragontools.core import windows_restart_policy as policy
    monkeypatch.setattr(policy.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(policy, "_USER_SHUTDOWN_ALLOWED_UNTIL", 0.0)
    assert not policy.user_initiated_shutdown_allowed()


def test_queue_order_keeps_actual_rows_and_rejects_foreign_paths(qtbot, tmp_path):
    from dragontools.gui.convert_widget_file_queue import FileListWidget
    from dragontools.gui.convert_widget_queue_window_actions import ConvertWidgetQueueWindowActionsMixin
    from PyQt6.QtCore import Qt
    rows = FileListWidget()
    qtbot.addWidget(rows)
    a, b, c, foreign = [str(tmp_path / name) for name in ("a.mkv", "b.mkv", "c.mkv", "foreign.mkv")]
    for path in [a, b, c]:
        assert rows.add_path(path)
    original = {path: rows.item_for_path(path) for path in rows.get_paths()}
    original[b].setToolTip("watch ownership metadata")
    original[b].setSelected(True)
    owner = SimpleNamespace(_ui=SimpleNamespace(file_list=rows),
        _guard_queue_edit_allowed=lambda _: True, _sync_queue_order=lambda: None)
    ConvertWidgetQueueWindowActionsMixin._apply_queue_window_order(owner, [b, foreign, b])
    assert rows.get_paths() == [b, a, c]
    assert all(rows.item_for_path(path) is item for path, item in original.items())
    assert original[b].toolTip() == "watch ownership metadata"
    assert original[b].isSelected()
    assert rows.item(0).data(Qt.ItemDataRole.UserRole) == b


def test_watch_replaced_source_with_same_size_and_mtime_is_new_revision(tmp_path):
    from dragontools.core.watch_folder import WatchFolderScanner, WatchFolderRule
    source = tmp_path / "Ü Episode.mkv"
    source.write_bytes(b"first")
    rule = WatchFolderRule("rule", "watch", str(tmp_path))
    scanner = WatchFolderScanner(stable_seconds=0)
    old = scanner.scan([rule], now=0)[0]
    scanner.acknowledge(old)
    stat = source.stat()
    replacement = tmp_path / "replacement.tmp"
    replacement.write_bytes(b"other")
    os.utime(replacement, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    os.replace(replacement, source)
    candidates = scanner.scan([rule], now=1)
    assert len(candidates) == 1
    assert candidates[0].signature != old.signature


def _watch_controller(qapp, tmp_path, monkeypatch, enqueue):
    from PyQt6.QtCore import QSettings
    from dragontools.gui import watch_folder_controller as module
    settings = QSettings(str(tmp_path / "watch.ini"), QSettings.Format.IniFormat)
    controller = module.WatchFolderController(settings=settings, enqueue_callback=enqueue)
    return controller, module


def _candidate(path="C:/Watch/Episode.mkv", signature="one", codec="h265"):
    from dragontools.core.watch_folder import WatchFolderCandidate
    return WatchFolderCandidate("rule", path, signature, codec, "", False)


def test_watch_callbacks_cannot_acknowledge_a_new_reservation(qapp, tmp_path, monkeypatch):
    callbacks = []
    def enqueue(**kwargs):
        callbacks.append(kwargs["completion_callback"])
        return kwargs["paths"]
    controller, _ = _watch_controller(qapp, tmp_path, monkeypatch, enqueue)
    old = _candidate()
    controller._handle_candidates([old])
    callbacks[0](old.path, False, "")
    new = replace(old, signature="new")
    controller._handle_candidates([new])
    callbacks[0](old.path, True, "elsewhere.mkv")
    assert controller._scanner.processed_state() == {}
    assert list(controller._pending.values()) == [new]
    callbacks[1](new.path, True, "elsewhere.mkv")
    assert list(controller._scanner.processed_state().values()) == ["new"]
    controller.stop(timeout_ms=0)


def test_watch_same_revision_cannot_acquire_another_codec_owner(qapp, tmp_path, monkeypatch):
    codecs = []
    def enqueue(**kwargs):
        codecs.append(kwargs["codec"])
        return kwargs["paths"]
    controller, _ = _watch_controller(qapp, tmp_path, monkeypatch, enqueue)
    old = _candidate()
    controller._handle_candidates([old])
    controller._handle_candidates([replace(old, codec="av1")])
    assert codecs == ["h265"]
    assert list(controller._pending.values()) == [old]
    controller.stop(timeout_ms=0)


def test_watch_intake_accepts_canonical_return_paths(qapp, tmp_path, monkeypatch):
    controller, _ = _watch_controller(qapp, tmp_path, monkeypatch,
        lambda **kwargs: [kwargs["paths"][0].upper().replace("/", "\\")])
    candidate = _candidate()
    controller._handle_candidates([candidate])
    assert list(controller._pending.values()) == [candidate]
    controller.stop(timeout_ms=0)


def test_missing_explicit_watch_profile_does_not_enqueue_defaults():
    from dragontools.gui.convert_widget_watch_intake import ConvertWidgetWatchMixin
    added = []
    class Owner(ConvertWidgetWatchMixin):
        def __init__(self):
            self._state = SimpleNamespace(file_overrides={}, thread=None)
            self.profile_manager = SimpleNamespace(data={})
            self.default_codec = "h265"
            self.file_list = SimpleNamespace(item_for_path=lambda _: None, add_path=lambda p: added.append(p) or True)
        def _is_queue_blocking_move_active(self): return False
        def _log(self, *args): pass
        def _refresh_queue_window(self): pass
    assert Owner().enqueue_watch_folder_files(["a.mkv"], profile_key="missing") == []
    assert added == []


def test_parallel_pending_start_handles_synchronous_completion(monkeypatch):
    module, _ = _install_parallel_fakes(monkeypatch)
    class ImmediateWorker(FakeWorker):
        def start(self):
            self.file_result.emit(self.files[0], self.files[0] + ".out", "✅")
            self.finished.emit()
    monkeypatch.setattr(module, "ConverterThread", ImmediateWorker)
    parent = _thread(module, ["a.mkv", "b.mkv", "c.mkv"], jobs=1)
    results, finished = [], []
    parent.file_result.connect(lambda *a: results.append(a))
    parent.finished.connect(lambda: finished.append(True))
    parent.start()
    assert [r[0] for r in results] == ["a.mkv", "b.mkv", "c.mkv"]
    assert parent._pending_files == []
    assert not parent.isRunning()
    assert finished == [True]


def test_parallel_launcher_rejects_already_owned_source(monkeypatch):
    module, _ = _install_parallel_fakes(monkeypatch)
    parent = _thread(module, [r"C:\Media\Episode.mkv"], jobs=1)
    parent.start()
    owner = FakeWorker.instances[0]
    with pytest.raises((RuntimeError, ValueError)):
        parent._start_child_worker([r"c:\media\EPISODE.MKV"])
    assert len(FakeWorker.instances) == 1
    assert list(parent._assigned.values()) == [owner]


@pytest.mark.parametrize("kind", ["result", "encode", "progress"])
def test_parallel_ignores_foreign_child_events(monkeypatch, kind):
    module, _ = _install_parallel_fakes(monkeypatch)
    parent = _thread(module, ["a.mkv", "b.mkv"], jobs=1)
    parent.start()
    child = FakeWorker.instances[0]
    results = []
    parent.file_result.connect(lambda *a: results.append(a))
    if kind == "result":
        child.file_result.emit("foreign.mkv", "foreign.out", "✅")
    elif kind == "encode":
        parent._on_child_encode_stage_complete(child, "foreign.mkv", "foreign.out")
    else:
        child.file_progress.emit("foreign.mkv", 80, None)
    assert parent._terminal_inputs == set()
    assert parent._file_progress_pct == {}
    assert parent._queue_state.dv_postprocessing_inputs == set()
    assert parent.encode_active_count() == 1
    assert results == []


@pytest.mark.parametrize("late", ["✅", "❌", "🧩", "progress", "encode"])
def test_parallel_terminal_events_are_monotonic_and_canonical(monkeypatch, late):
    module, _ = _install_parallel_fakes(monkeypatch)
    path = r"C:\Media\Episode.mkv"
    alias = r"c:\media\EPISODE.MKV"
    parent = _thread(module, [path], jobs=1)
    parent.start()
    child = FakeWorker.instances[0]
    results = []
    parent.file_result.connect(lambda *a: results.append(a))
    child.file_result.emit(alias, "episode.out", "✅")
    if late == "progress":
        child.file_progress.emit(path, 60, None)
    elif late == "encode":
        parent._on_child_encode_stage_complete(child, path, "episode.out")
    else:
        child.file_result.emit(path, "episode.out", late)
    child._running = False
    child.finished.emit()
    assert results == [(path, "episode.out", "✅")]
    assert parent._terminal_inputs == {path}
    assert parent._file_progress_pct == {}
    assert not parent.isRunning()


def test_parallel_abort_reaches_all_children_after_one_fails(monkeypatch):
    module, _ = _install_parallel_fakes(monkeypatch)
    parent = _thread(module, ["a.mkv", "b.mkv"], jobs=2)
    parent.start()
    first, second = FakeWorker.instances
    def fail(*a):
        raise RuntimeError("first child abort failed")
    first.request_abort = fail
    parent.request_abort()
    assert second.abort_requested


def test_parallel_logger_failure_does_not_leave_phantom_running_state(monkeypatch):
    module, logger = _install_parallel_fakes(monkeypatch)
    parent = _thread(module, ["a.mkv"], jobs=1)
    def fail(**kwargs):
        raise RuntimeError("logger unavailable")
    logger.header = fail
    parent.start()
    assert len(FakeWorker.instances) == 1
    assert parent.isRunning()


def test_parallel_child_options_are_detached_from_parent(monkeypatch):
    module, _ = _install_parallel_fakes(monkeypatch)
    parent = _thread(module, ["a.mkv", "b.mkv"], jobs=2)
    parent.encoder_options["nested"] = {"value": 1}
    parent.file_overrides["a.mkv"] = {"nested": {"value": 2}}
    parent.start()
    first, second = FakeWorker.instances
    first.config.encoder_options["nested"]["value"] = 8
    first.config.file_overrides["a.mkv"]["nested"]["value"] = 9
    assert parent.encoder_options["nested"]["value"] == 1
    assert second.config.encoder_options["nested"]["value"] == 1
    assert parent.file_overrides["a.mkv"]["nested"]["value"] == 2


def test_parallel_caller_config_cannot_change_run_after_construction(monkeypatch):
    module, _ = _install_parallel_fakes(monkeypatch)
    from dragontools.worker.converter_config import ConverterConfig
    config = ConverterConfig("h265", 23, "medium", "original", False)
    parent = module.ParallelConverterThread(["a.mkv"], config, parallel_jobs=1)
    config.codec = "av1"
    parent.start()
    assert FakeWorker.instances[0].config.codec == "h265"


def test_dv_gate_rechecks_abort_after_slot_acquired(monkeypatch):
    from dragontools.worker.dv_postprocess_gate import DVPostprocessGate
    gate = DVPostprocessGate(1)
    aborted = [False]
    original = gate._semaphore.acquire
    def acquire(**kwargs):
        result = original(**kwargs)
        aborted[0] = True
        return result
    monkeypatch.setattr(gate._semaphore, "acquire", acquire)
    assert not gate.acquire(abort_requested=lambda: aborted[0])
    assert gate.active == 0
    assert original(blocking=False)
    gate._semaphore.release()


def test_parallel_duplicate_finished_does_not_publish_changed_artifacts(monkeypatch):
    module, _ = _install_parallel_fakes(monkeypatch)
    parent = _thread(module, ["a.mkv"], jobs=1)
    parent.start()
    child = FakeWorker.instances[0]
    child._sidecar_outputs["a.mkv"] = ["original.nfo"]
    child.file_result.emit("a.mkv", "a.out", "✅")
    child._running = False
    child.finished.emit()
    child._sidecar_outputs["a.mkv"] = ["foreign.nfo"]
    child.finished.emit()
    assert parent._sidecar_outputs["a.mkv"] == ["original.nfo"]


def test_parallel_foreign_artifacts_are_not_imported_at_child_finish(monkeypatch):
    module, _ = _install_parallel_fakes(monkeypatch)
    parent = _thread(module, ["a.mkv"], jobs=1)
    parent.start()
    child = FakeWorker.instances[0]
    child._sidecar_outputs["foreign.mkv"] = ["foreign.nfo"]
    child.file_result.emit("a.mkv", "a.out", "✅")
    child._running = False
    child.finished.emit()
    assert "foreign.mkv" not in parent._sidecar_outputs


def test_parallel_artifacts_follow_canonical_terminal_input(monkeypatch):
    module, _ = _install_parallel_fakes(monkeypatch)
    source, alias = r"C:\Media\A.mkv", r"c:\media\a.MKV"
    parent = _thread(module, [source], jobs=1)
    parent.start()
    child = FakeWorker.instances[0]
    child._sidecar_outputs[alias] = ["episode.nfo"]
    child.file_result.emit(alias, "episode.out", "✅")
    assert parent._sidecar_outputs == {source: ["episode.nfo"]}


def test_shutdown_wait_budget_includes_abort_request_time(monkeypatch):
    from dragontools.gui import application_shutdown as module
    stamp, waits = [10.0], []
    monkeypatch.setattr(module.time, "monotonic", lambda: stamp[0])
    def abort(mode):
        stamp[0] += 2
    worker = SimpleNamespace(isRunning=lambda: True, request_abort=abort,
        wait=lambda budget: waits.append(budget) or False)
    assert not module.shutdown_workers([worker], timeout_ms=1000).ok
    assert waits == [0]
