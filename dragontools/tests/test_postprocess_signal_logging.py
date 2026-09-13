from __future__ import annotations

import threading


class FakeQtSignal:
    """Signal-like object reproducing pyqtBoundSignal call semantics."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    def emit(self, message: str) -> None:
        self.messages.append(str(message))

    def __call__(self, *_args, **_kwargs):
        raise TypeError("native Qt signal is not callable")


def test_log_dispatch_uses_emit_for_qt_signal_like_object():
    from dragontools.worker.log_dispatch import dispatch_log

    signal = FakeQtSignal()

    assert dispatch_log(signal, "Hallo", "warn") is True
    assert signal.messages == ["Hallo"]


def test_log_dispatch_preserves_level_for_worker_style_callable():
    from dragontools.worker.log_dispatch import dispatch_log

    calls = []

    def worker_log(message, level="info"):
        calls.append((message, level))

    assert dispatch_log(worker_log, "Warnung", "warn") is True
    assert calls == [("Warnung", "warn")]


def test_trickplay_logger_accepts_qt_signal_like_object():
    from dragontools.worker.trickplay_service import TrickplayGenerator

    signal = FakeQtSignal()
    generator = TrickplayGenerator(ffmpeg_path="ffmpeg", log=signal)

    generator._info("info")
    generator._warn("warn")

    assert signal.messages == ["info", "warn"]


def test_async_postprocess_with_qt_signal_log_runs_exactly_once(tmp_path):
    from dragontools.worker.postprocess_async import AsyncPostProcessCoordinator
    from dragontools.worker.postprocess_models import PostProcessRunResult

    output = tmp_path / "film.mkv"
    output.write_bytes(b"video")
    signal = FakeQtSignal()
    release = threading.Event()
    run_count = 0
    run_lock = threading.Lock()
    events = []

    class FakeService:
        def run_result(self, *, input_path, output_path):
            nonlocal run_count
            with run_lock:
                run_count += 1
            assert release.wait(timeout=3)
            return PostProcessRunResult([], [])

    class ResultService:
        def emit_file_progress(self, input_path, pct):
            events.append(("progress", input_path, pct))

        def emit_file_result(self, input_path, output_path, status):
            events.append(("result", input_path, output_path, status))

    coordinator = AsyncPostProcessCoordinator(
        settings=None,
        tools=object(),
        log=signal,
        service_factory=FakeService,
    )

    assert coordinator.submit(
        input_path="in.mkv",
        output_path=str(output),
        existing_sidecars=[],
        sidecar_outputs={},
        postprocess_outputs={},
        result_service=ResultService(),
    ) is True

    release.set()
    coordinator.wait_for_all()

    assert run_count == 1
    assert events.count(("progress", "in.mkv", 100)) == 1
    assert events.count(("result", "in.mkv", str(output), "✅")) == 1
    assert any("im Hintergrund gestartet" in message for message in signal.messages)
    assert any("abgeschlossen" in message for message in signal.messages)


def test_async_postprocess_completion_survives_bookkeeping_failure(tmp_path):
    from dragontools.worker.postprocess_async import AsyncPostProcessCoordinator
    from dragontools.worker.postprocess_models import PostProcessRunResult

    output = tmp_path / "film.mkv"
    output.write_bytes(b"video")
    events = []

    class FakeService:
        def run_result(self, *, input_path, output_path):
            return PostProcessRunResult([], [{"kind": "nfo", "status": "created"}])

    class BrokenMapping(dict):
        def __setitem__(self, key, value):
            raise RuntimeError("bookkeeping kaputt")

    class ResultService:
        def emit_file_progress(self, input_path, pct):
            events.append(("progress", input_path, pct))

        def emit_file_result(self, input_path, output_path, status):
            events.append(("result", input_path, output_path, status))

    coordinator = AsyncPostProcessCoordinator(
        settings=None,
        tools=object(),
        log=lambda _message: None,
        service_factory=FakeService,
    )

    assert coordinator.submit(
        input_path="in.mkv",
        output_path=str(output),
        existing_sidecars=[],
        sidecar_outputs={},
        postprocess_outputs=BrokenMapping(),
        result_service=ResultService(),
    ) is True
    coordinator.wait_for_all()

    assert events.count(("progress", "in.mkv", 100)) == 1
    assert events.count(("result", "in.mkv", str(output), "✅")) == 1


def test_workflow_does_not_start_sync_fallback_after_async_qt_signal_logging(tmp_path):
    from types import SimpleNamespace

    from dragontools.worker.postprocess_async import AsyncPostProcessCoordinator
    from dragontools.worker.postprocess_models import PostProcessRunResult
    from dragontools.worker.workflow_output_commit import WorkflowOutputCommitCoordinator

    output = tmp_path / "film.mkv"
    output.write_bytes(b"video")
    signal = FakeQtSignal()
    async_runs = 0
    sync_runs = 0

    class AsyncService:
        def run_result(self, *, input_path, output_path):
            nonlocal async_runs
            async_runs += 1
            return PostProcessRunResult([], [])

    class SyncService:
        def is_enabled(self):
            return True

        def run(self, *, input_path, output_path):
            nonlocal sync_runs
            sync_runs += 1
            return []

    class ResultService:
        def emit_file_progress(self, *_args):
            return None

        def emit_file_result(self, *_args):
            return None

    coordinator = AsyncPostProcessCoordinator(
        settings=None,
        tools=object(),
        log=signal,
        service_factory=AsyncService,
    )
    workflow = WorkflowOutputCommitCoordinator(
        replace_service=object(),
        logger=SimpleNamespace(warn=lambda _message: None),
        result_service=ResultService(),
        sidecar_outputs={},
        postprocess_outputs={},
        postprocess_service=SyncService(),
        postprocess_coordinator=coordinator,
    )
    ctx = SimpleNamespace(
        final_output_path=str(output),
        output_path=str(output),
        input_path="in.mkv",
        sidecar_paths=[],
    )

    assert workflow.start_postprocess(ctx) is True
    coordinator.wait_for_all()

    assert async_runs == 1
    assert sync_runs == 0
