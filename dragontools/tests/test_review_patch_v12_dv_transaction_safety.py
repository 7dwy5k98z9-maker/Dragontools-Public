from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from dragontools.core.output_replace import OutputCommitResult
from dragontools.worker.converter_queue_state import ConverterQueueState
from dragontools.worker.dv5_encode_fallback import DV5EncodeFallbackRunner
from dragontools.worker.dv_remux_file_dispatcher import DVRemuxFileDispatcher
from dragontools.worker.dv_remux_job import DVRemuxJobRunner
from dragontools.worker.dv_remux_output import DVOutputInstallResult, DVOutputManager
from dragontools.worker.dv_result_contract import fail_unfinished_dv_inputs, mark_dv_terminal
from dragontools.worker.workflow_output_commit import WorkflowOutputCommitCoordinator


class _Signal:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


class _Pipeline:
    last_expected_contract = None

    def __init__(self, staging: Path):
        self.staging = staging

    def run(self, **_kwargs):
        self.staging.parent.mkdir(parents=True, exist_ok=True)
        self.staging.write_bytes(b"dv-output" * 256)
        return True


class _NoSubtitles:
    def export_sidecars_result(self, **_kwargs):
        return SimpleNamespace(exported_paths=[], complete=True, failure_summary=lambda: "")


def _worker(**overrides):
    values = dict(
        overwrite_original=True,
        container="mp4",
        subtitle_rules={},
        abort_requested=False,
        abort_type=None,
        tools=SimpleNamespace(),
        _postprocess_service=None,
        _sidecar_outputs={},
        _postprocess_outputs={},
        _failure_details={},
        worker_event=_Signal(),
        file_result=_Signal(),
        file_progress=_Signal(),
        log=lambda *_a: None,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _runner(worker, source: Path, staging: Path, output_manager, *, emit_success=None):
    return DVRemuxJobRunner(
        worker,
        process_runner=SimpleNamespace(),
        pipeline=_Pipeline(staging),
        output_manager=output_manager,
        subtitle_service=_NoSubtitles(),
        prepare_metadata=lambda _p: (
            source.name,
            SimpleNamespace(subtitle_streams=[], analysis_warnings=[]),
            1000,
            None,
        ),
        emit_success=emit_success,
    )


def test_committed_dv_output_survives_exception_after_video_commit(tmp_path):
    source = tmp_path / "Film.mkv"
    staging = tmp_path / "__temp_dv_remux__" / "Film.mp4"
    final = tmp_path / "Film.mp4"
    source.write_bytes(b"original")
    cleanup_calls = []

    class OutputManager:
        def build_output_path(self, _input):
            return str(staging)

        def verify_output(self, **_kwargs):
            return True

        def replace_output_if_needed(self, input_path, output_path):
            Path(input_path).unlink()
            Path(output_path).replace(final)
            return DVOutputInstallResult(True, str(final), committed=True)

        def cleanup_incomplete(self, *args):
            cleanup_calls.append(args)

    runner = _runner(
        _worker(), source, staging, OutputManager(),
        emit_success=lambda *_a: (_ for _ in ()).throw(RuntimeError("late signal failure")),
    )

    assert runner.run(str(source)) is False
    assert not source.exists()
    assert final.exists(), "a committed video must never be removed by incomplete cleanup"
    assert cleanup_calls == []


def test_abort_after_source_trickplay_blocks_destructive_dv_replace(tmp_path):
    source = tmp_path / "Film.mkv"
    staging = tmp_path / "__temp_dv_remux__" / "Film.mp4"
    source.write_bytes(b"original")
    replaced = []
    cleaned = []
    worker = _worker()

    class Postprocess:
        def prepare_source_trickplay(self, **_kwargs):
            worker.abort_requested = True
            worker.abort_type = "sofort"
            return SimpleNamespace(created_paths=[], items=[])

    class OutputManager:
        def build_output_path(self, _input):
            return str(staging)

        def verify_output(self, **_kwargs):
            return True

        def replace_output_if_needed(self, *_args):
            replaced.append(True)
            raise AssertionError("replace must not run after immediate abort")

        def cleanup_incomplete(self, *_args):
            cleaned.append(True)
            if staging.exists():
                staging.unlink()

    worker._postprocess_service = Postprocess()
    runner = _runner(worker, source, staging, OutputManager())

    assert runner.run(str(source)) is False
    assert source.exists()
    assert replaced == []
    assert cleaned == [True]
    assert worker._failure_details[str(source)]["strategy"] == "abort_before_commit"


def test_cleanup_pending_is_terminal_warning_and_committed_output_is_preserved(tmp_path):
    source = tmp_path / "Film.mkv"
    staging = tmp_path / "__temp_dv_remux__" / "Film.mp4"
    final = tmp_path / "Film.mp4"
    source.write_bytes(b"original")
    cleanup_calls = []

    class OutputManager:
        def build_output_path(self, _input):
            return str(staging)

        def verify_output(self, **_kwargs):
            return True

        def replace_output_if_needed(self, input_path, output_path):
            Path(output_path).replace(final)
            return DVOutputInstallResult(
                True,
                str(final),
                committed=True,
                cleanup_pending=True,
                cleanup_message="Original ist noch gesperrt",
            )

        def cleanup_incomplete(self, *args):
            cleanup_calls.append(args)

    worker = _worker()
    runner = _runner(worker, source, staging, OutputManager())

    assert runner.run(str(source)) is False
    assert final.exists()
    assert cleanup_calls == []
    assert worker.file_result.calls[-1] == (str(source), str(final), "⚠️")
    assert worker._failure_details[str(source)]["strategy"] == "cleanup_pending"
    assert "gesperrt" in worker._failure_details[str(source)]["message"]


def test_preserved_archive_output_is_never_treated_as_incomplete_temp(tmp_path):
    source = tmp_path / "Film.mkv"
    staging = tmp_path / "__temp_dv_remux__" / "Film.mp4"
    archive = tmp_path / "Archiv" / "Film.mp4"
    source.write_bytes(b"original")
    cleanup_calls = []

    class OutputManager:
        def build_output_path(self, _input):
            return str(staging)

        def verify_output(self, **_kwargs):
            return True

        def replace_output_if_needed(self, _input, output_path):
            archive.parent.mkdir()
            Path(output_path).replace(archive)
            return DVOutputInstallResult(False, str(archive), preserved=True)

        def cleanup_incomplete(self, *args):
            cleanup_calls.append(args)

    worker = _worker()
    runner = _runner(worker, source, staging, OutputManager())

    assert runner.run(str(source)) is False
    assert archive.exists()
    assert source.exists()
    assert cleanup_calls == []
    assert worker.file_result.calls[-1] == (str(source), str(archive), "⚠️")


def test_dv_output_manager_preserves_full_cleanup_pending_commit_result(tmp_path, monkeypatch):
    source = tmp_path / "Film.mkv"
    staging = tmp_path / "__temp_dv_remux__" / "Film.mp4"
    final = tmp_path / "Film.mp4"
    source.write_bytes(b"original")
    staging.parent.mkdir()
    staging.write_bytes(b"converted" * 256)
    backup = tmp_path / "Film.mkv.dragontools_backup"

    worker = _worker(_log=lambda *_a: None)
    manager = DVOutputManager(worker)
    monkeypatch.setattr(
        "dragontools.worker.dv_remux_output.validate_output_size_policy",
        lambda **_kwargs: (True, None),
    )
    monkeypatch.setattr(
        "dragontools.worker.dv_remux_output.commit_staged_output",
        lambda **_kwargs: OutputCommitResult(
            destination=final,
            cleanup_pending=True,
            cleanup_message="backup locked",
            backup_path=backup,
        ),
    )

    result = manager.replace_output_if_needed(str(source), str(staging))
    assert result.committed is True
    assert result.cleanup_pending is True
    assert result.cleanup_message == "backup locked"
    assert result.backup_path == str(backup)
    ok, path = result  # legacy adapter remains supported
    assert ok is True and path == str(final)


def test_dispatch_analysis_failure_uses_structured_dv_failure_contract(tmp_path):
    source = tmp_path / "bad.mkv"
    source.write_bytes(b"x")
    worker = _worker()
    worker.prepare_remux_metadata = lambda _p: (_ for _ in ()).throw(RuntimeError("probe broke"))
    dispatcher = DVRemuxFileDispatcher(worker)

    assert dispatcher.run(str(source)) is False
    assert worker.file_result.calls[-1][2] == "❌"
    assert worker._failure_details[str(source)]["strategy"] == "analysis"
    assert "probe broke" in worker._failure_details[str(source)]["message"]


def test_dv5_fallback_without_config_emits_one_terminal_failure(tmp_path):
    source = tmp_path / "p5.mkv"
    source.write_bytes(b"x")
    worker = _worker(_logger=SimpleNamespace())
    runner = DV5EncodeFallbackRunner(worker, None)

    assert runner.run(str(source)) is False
    assert worker.file_result.calls == [(str(source), str(source), "❌")]
    assert worker._failure_details[str(source)]["strategy"] == "dv5_fallback_config"


def test_top_level_dv_failure_marks_only_unfinished_queue_items():
    worker = _worker()
    worker._queue = ConverterQueueState(["a.mkv", "b.mkv", "c.mkv"])
    worker._queue.current_file = "a.mkv"
    worker._queue.done_files.add("c.mkv")
    mark_dv_terminal(worker, "a.mkv", "✅")

    emitted = fail_unfinished_dv_inputs(worker, "worker exploded", stage="worker")

    assert emitted == ["b.mkv"]
    assert worker.file_result.calls == [("b.mkv", "b.mkv", "❌")]
    assert worker._failure_details["b.mkv"]["strategy"] == "worker"


def test_normal_workflow_abort_after_source_trickplay_never_calls_replace(tmp_path):
    aborted = {"value": False}
    replace_calls = []

    class Postprocess:
        def prepare_source_trickplay(self, **_kwargs):
            aborted["value"] = True
            return SimpleNamespace(created_paths=[], items=[])

    class Replace:
        def replace(self, **_kwargs):
            replace_calls.append(True)
            return _kwargs["output_path"]

    coordinator = WorkflowOutputCommitCoordinator(
        replace_service=Replace(),
        logger=SimpleNamespace(warn=lambda *_a: None),
        result_service=SimpleNamespace(),
        sidecar_outputs={},
        postprocess_outputs={},
        postprocess_service=Postprocess(),
        abort_check=lambda: aborted["value"],
    )
    ctx = SimpleNamespace(
        input_path=str(tmp_path / "Film.mkv"),
        output_path=str(tmp_path / "temp.mp4"),
        final_output_path=None,
        container="mp4",
        replace_original=True,
        sidecar_paths=[],
        prepared_source_trickplay=None,
    )

    with pytest.raises(RuntimeError, match="Sofort-Abbruch"):
        coordinator.replace(ctx)
    assert replace_calls == []
    assert ctx.prepared_source_trickplay is None
