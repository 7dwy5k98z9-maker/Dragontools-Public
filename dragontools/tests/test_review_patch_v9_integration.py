# -*- coding: utf-8 -*-
from __future__ import annotations

import threading
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace


def test_async_postprocess_announces_pending_before_immediate_completion():
    from dragontools.worker.postprocess_async import AsyncPostProcessCoordinator
    from dragontools.worker.postprocess_models import PostProcessRunResult

    class ImmediateExecutor:
        def submit(self, fn, **kwargs):
            future = Future()
            future.set_result(fn(**kwargs))
            return future

    class Service:
        def run_result(self, **_kwargs):
            return PostProcessRunResult([], [])

    events = []
    result_service = SimpleNamespace(
        emit_file_progress=lambda *_args: None,
        emit_file_result=lambda input_path, output_path, status: events.append(
            (input_path, output_path, status)
        ),
    )
    coordinator = object.__new__(AsyncPostProcessCoordinator)
    coordinator.settings = object()
    coordinator.tools = object()
    coordinator.log = lambda *_args: None
    coordinator.worker = None
    coordinator._service_factory = Service
    coordinator._executor = ImmediateExecutor()
    coordinator._futures = []
    coordinator._lock = threading.Lock()
    coordinator._shutdown = False

    assert coordinator.submit(
        input_path="source.mkv",
        output_path="output.mkv",
        existing_sidecars=[],
        sidecar_outputs={},
        postprocess_outputs={},
        result_service=result_service,
    ) is True
    assert [status for _src, _dst, status in events] == ["🧩", "✅"]


def test_async_optional_postprocess_error_stays_successful_terminal_result():
    from dragontools.worker.postprocess_async import AsyncPostProcessCoordinator
    from dragontools.worker.postprocess_models import PostProcessRunResult

    future = Future()
    future.set_result(PostProcessRunResult([], [{
        "kind": "trickplay",
        "status": "error",
        "path": "",
        "message": "boom",
    }]))
    events = []
    coordinator = object.__new__(AsyncPostProcessCoordinator)
    coordinator.log = lambda *_args: None

    coordinator._complete(
        future,
        input_path="source.mkv",
        output_path="output.mkv",
        existing_sidecars=[],
        sidecar_outputs={},
        postprocess_outputs={},
        result_service=SimpleNamespace(
            emit_file_progress=lambda *_args: None,
            emit_file_result=lambda _src, _dst, status: events.append(status),
        ),
    )
    assert events == ["✅"]


def test_gui_late_pending_cannot_resurrect_completed_input():
    from dragontools.gui.conversion_result_file_events import ConversionResultFileEventsMixin

    class Harness(ConversionResultFileEventsMixin):
        def __init__(self):
            self._state = SimpleNamespace(
                pending_postprocess_inputs=set(),
                completed_inputs={"episode.mkv"},
            )
            self._ui = SimpleNamespace(file_list=object())
            self.refresh_count = 0

        def _set_file_list_item_text(self, *_args):
            pass

        def _refresh_queue(self):
            self.refresh_count += 1

    h = Harness()
    h.on_file_result("episode.mkv", "episode.mkv", "🧩")
    assert h._state.pending_postprocess_inputs == set()
    assert h.refresh_count == 1


def test_parallel_late_pending_cannot_resurrect_terminal_input():
    from dragontools.worker.parallel_child_result_coordinator import ParallelChildResultCoordinator

    queue = SimpleNamespace(
        postprocessing_inputs=set(),
        terminal_inputs={"episode.mkv"},
        file_progress_pct={},
    )
    registry = SimpleNamespace(active_workers=set(), postprocessing_workers=set(), sync_child_maps=lambda *_args: None)
    coordinator = ParallelChildResultCoordinator(
        registry=registry,
        queue_state=queue,
        result_state=SimpleNamespace(),
    )
    forwarded = []
    coordinator.on_file_result(
        object(),
        "episode.mkv",
        "episode.mkv",
        "🧩",
        abort_requested=False,
        start_pending_workers=lambda: None,
        emit_file_result=lambda *args: forwarded.append(args),
        emit_aggregate_progress=lambda: None,
        finish_if_done=lambda: None,
    )
    assert queue.postprocessing_inputs == set()
    assert forwarded == []


def test_dv5_fallback_publishes_child_sidecars_before_terminal_result(monkeypatch):
    import dragontools.worker.dv5_encode_fallback as module
    from dragontools.worker.converter_config import ConverterConfig

    class Signal:
        def __init__(self):
            self.callbacks = []

        def connect(self, callback):
            self.callbacks.append(callback)

        def emit(self, *args):
            for callback in list(self.callbacks):
                callback(*args)

    class FakeChild:
        def __init__(self, files, config, shared_logger=None):
            self.file_progress = Signal()
            self.file_result = Signal()
            self.event = Signal()
            self.dv_crop_decision_requested = Signal()
            self.erfolgreich = 0
            self.fehlgeschlagen = 0
            self._session_state = SimpleNamespace(
                sidecar_outputs={}, postprocess_outputs={}, failure_details={}
            )

        def run(self):
            self._session_state.sidecar_outputs["movie.mkv"] = ["movie.nfo", "movie.trickplay"]
            self._session_state.postprocess_outputs["movie.mkv"] = [{"kind": "nfo", "status": "created"}]
            self.erfolgreich = 1
            self.file_result.emit("movie.mkv", "movie_converted.mkv", "✅")

        def request_abort(self, *_args):
            pass

        def pause(self):
            pass

        def resume(self):
            pass

    monkeypatch.setattr(module, "ConverterThread", FakeChild)
    terminal_snapshots = []

    class OuterSignal:
        def emit(self, *args):
            if len(args) == 3 and args[-1] == "✅":
                terminal_snapshots.append(list(worker._sidecar_outputs.get("movie.mkv", [])))

    worker = SimpleNamespace(
        _logger=object(),
        _active_fallback_worker=None,
        file_overrides={},
        _sidecar_outputs={},
        _postprocess_outputs={},
        _failure_details={},
        file_progress=OuterSignal(),
        file_result=OuterSignal(),
        event=OuterSignal(),
        dv_crop_decision_requested=OuterSignal(),
        log=lambda *_args: None,
    )
    config = ConverterConfig(
        codec="h265", crf=23, preset="p6", scale_mode="original",
        overwrite_original=False, encoder_options={},
    )
    assert module.DV5EncodeFallbackRunner(worker, config).run("movie.mkv") is True
    assert terminal_snapshots == [["movie.nfo", "movie.trickplay"]]
    assert worker._postprocess_outputs["movie.mkv"][0]["kind"] == "nfo"


def test_direct_dv_remux_merges_optional_postprocess_outputs():
    from dragontools.worker.dv_remux_job import DVRemuxJobRunner
    from dragontools.worker.postprocess_models import PostProcessRunResult

    logs = []
    worker = SimpleNamespace(
        _postprocess_service=SimpleNamespace(
            is_enabled=lambda: True,
            run_result=lambda **_kwargs: PostProcessRunResult(
                ["movie.nfo", "movie.trickplay"],
                [
                    {"kind": "nfo", "status": "created", "path": "movie.nfo", "message": ""},
                    {"kind": "trickplay", "status": "error", "path": "", "message": "optional failure"},
                ],
            ),
        ),
        _sidecar_outputs={"movie.mkv": ["movie.de.srt"]},
        _postprocess_outputs={},
        log=lambda message, level="info": logs.append((level, message)),
    )
    runner = object.__new__(DVRemuxJobRunner)
    runner.worker = worker
    runner._run_optional_postprocess("movie.mkv", "movie.dv.mkv")

    assert worker._sidecar_outputs["movie.mkv"] == [
        "movie.de.srt", "movie.nfo", "movie.trickplay"
    ]
    assert worker._postprocess_outputs["movie.mkv"][1]["status"] == "error"
    assert any(level == "warn" for level, _msg in logs)


def test_move_sidecars_follow_conflict_renamed_video_stem(tmp_path):
    from dragontools.core.move_file_service import MoveFileService
    from dragontools.core.move_sidecars import MoveSidecarService

    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    source_dir.mkdir()
    target_dir.mkdir()
    subtitle = source_dir / "Film.de.srt"
    nfo = source_dir / "Film.nfo"
    trickplay = source_dir / "Film.trickplay"
    subtitle.write_text("sub", encoding="utf-8")
    nfo.write_text("<movie/>", encoding="utf-8")
    trickplay.mkdir()
    (trickplay / "0.jpg").write_bytes(b"jpg")

    file_service = MoveFileService(
        conflict_mode="skip",
        log=lambda *_args: None,
        wait=lambda: None,
        abort_immediately=lambda: False,
        journal=None,
    )
    service = MoveSidecarService(
        filme_path="",
        trickplay_conflict_mode="skip",
        nfo_movie_target_name="movie.nfo",
        move_file=file_service.move,
        log=lambda *_args: None,
        append_report=lambda *_args: None,
        set_last_result=lambda *_args: None,
    )
    result = service.move_sidecars(
        str(source_dir / "Film.mkv"),
        str(target_dir),
        [str(subtitle), str(nfo), str(trickplay)],
        dest_video_path=str(target_dir / "Film_01.mkv"),
    )
    assert result["ok"] is True
    assert (target_dir / "Film_01.de.srt").exists()
    assert (target_dir / "Film_01.nfo").exists()
    assert (target_dir / "Film_01.trickplay" / "0.jpg").exists()
    assert not (target_dir / "Film.de.srt").exists()


def test_move_completion_passes_actual_video_destination_to_sidecars(tmp_path):
    from dragontools.worker.move_completion_service import MoveCompletionService

    captured = {}

    class Journal:
        def mark_video_committed(self, *_args, **_kwargs):
            pass

        def finish_file(self, *_args, **_kwargs):
            pass

    service = MoveCompletionService(
        journal=Journal(),
        move_sidecars=lambda source, target, dest: captured.update(
            source=source, target=target, dest=dest
        ) or {"ok": True},
        record_media_library_move=lambda *_args: None,
        append_move_report=lambda *_args: None,
        log=lambda *_args: None,
    )
    dest = tmp_path / "target" / "Film_01.mkv"
    outcome = service.complete(
        journal_source="Film.mkv",
        sidecar_key="Film.mkv",
        target_dir=str(dest.parent),
        original_source="Film.mkv",
        move_result={"ok": True, "dest_path": str(dest)},
    )
    assert outcome.error is False
    assert captured["dest"] == str(dest)


def test_recovery_promotes_video_pending_to_companion_resume_when_sidecars_exist(tmp_path):
    from dragontools.core.move_journal import build_move_resume_plan, recover_interrupted_backups

    source = tmp_path / "source" / "Film.mkv"
    dest = tmp_path / "target" / "Film_01.mkv"
    sidecar = tmp_path / "source" / "Film.nfo"
    dest.parent.mkdir(parents=True)
    sidecar.parent.mkdir(parents=True)
    dest.write_bytes(b"video")
    sidecar.write_text("<movie/>", encoding="utf-8")

    data = {
        "files": {
            str(source): {
                "status": "running",
                "phase": "video_pending",
                "dest_path": str(dest),
                "target_dir": str(dest.parent),
                "backup_pairs": [],
                "cleanup_pending": False,
            }
        },
        "sidecar_outputs_by_video": {str(source): [str(sidecar)]},
    }
    result = recover_interrupted_backups(data)
    row = data["files"][str(source)]
    assert result["completed"] == 0
    assert row["status"] == "running"
    assert row["phase"] == "sidecars_pending"

    plan = build_move_resume_plan(data)
    assert plan["files"] == [str(dest)]
    assert plan["companion_resume_sources"] == {str(dest): str(source)}
    assert plan["sidecar_outputs_by_video"][str(dest)] == [str(sidecar)]
