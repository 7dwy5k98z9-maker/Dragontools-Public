from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from dragontools.core.conversion_artifacts import ConversionArtifactBundle
from dragontools.core.move_sidecars import MoveSidecarService
from dragontools.gui.conversion_session_state import ConversionSessionState
from dragontools.worker.dv_remux_job import DVRemuxJobRunner
from dragontools.worker.move_completion_service import MoveCompletionService
from dragontools.worker.postprocess_models import NfoSettings, PostProcessConfig, PostProcessRunResult
from dragontools.worker.postprocess_runner import PostProcessService
from dragontools.worker.trickplay_models import TrickplaySettings


class _Signal:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


class _Journal:
    def __init__(self):
        self.video_commits = []
        self.finishes = []

    def mark_video_committed(self, source, **kwargs):
        self.video_commits.append((source, kwargs))

    def finish_file(self, source, **kwargs):
        self.finishes.append((source, kwargs))


def test_rename_recovery_keeps_original_stem_for_companion_rebase(tmp_path):
    source = tmp_path / "source" / "Film.mkv"
    source.parent.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    committed_video = target / "Film_01.mkv"
    committed_video.write_bytes(b"video")
    sidecar = source.with_name("Film.de.srt")
    sidecar.write_text("sub", encoding="utf-8")

    captured = {}

    def move_sidecars(sidecar_key, target_dir, dest_path, source_video_path):
        captured.update(
            sidecar_key=sidecar_key,
            target_dir=target_dir,
            dest_path=dest_path,
            source_video_path=source_video_path,
        )
        service = MoveSidecarService(
            filme_path="",
            trickplay_conflict_mode="skip",
            nfo_movie_target_name="stem",
            move_file=lambda *_a, **_k: (True, {}),
            log=lambda *_a: None,
            append_report=lambda *_a, **_k: None,
            set_last_result=lambda *_a: None,
        )
        assert service.sidecar_dest_name(
            sidecar,
            str(target),
            video_path=source_video_path,
            dest_video_path=dest_path,
        ) == "Film_01.de.srt"
        return {"ok": True, "failed": 0}

    journal = _Journal()
    completion = MoveCompletionService(
        journal=journal,
        move_sidecars=move_sidecars,
        record_media_library_move=lambda *_a: None,
        append_move_report=lambda *_a: None,
        log=lambda *_a: None,
    )
    outcome = completion.complete(
        journal_source=str(committed_video),
        sidecar_key=str(committed_video),
        target_dir=str(target),
        original_source=str(source),
        move_result={"dest_path": str(committed_video), "ok": True},
    )

    assert not outcome.error
    assert captured["sidecar_key"] == str(committed_video)
    assert captured["source_video_path"] == str(source)


def test_source_trickplay_is_prepared_before_original_can_be_replaced(tmp_path, monkeypatch):
    source = tmp_path / "Film.mkv"
    final_output = tmp_path / "Film.mp4"
    source.write_bytes(b"source")
    calls = []

    cfg = PostProcessConfig(
        nfo=NfoSettings(enabled=False),
        trickplay=TrickplaySettings(enabled=True, source_mode="source"),
    )
    monkeypatch.setattr("dragontools.worker.postprocess_runner.config_from_settings", lambda _s: cfg)

    def fake_generate(self, video_path, settings, *, target_video_path=None):
        calls.append((Path(video_path), Path(target_video_path)))
        assert Path(video_path).exists(), "original must still exist during source trickplay"
        root = Path(target_video_path).with_name(f"{Path(target_video_path).stem}.trickplay")
        root.mkdir(exist_ok=True)
        (root / "1.jpg").write_bytes(b"jpg")
        return root

    monkeypatch.setattr("dragontools.worker.postprocess_runner.TrickplayGenerator.generate", fake_generate)
    service = PostProcessService(
        settings=object(),
        tools=SimpleNamespace(ffmpeg="ffmpeg", ffprobe="ffprobe"),
        log=lambda *_a: None,
    )

    prepared = service.prepare_source_trickplay(
        input_path=str(source), output_path=str(final_output)
    )
    assert prepared.created_paths == [str(tmp_path / "Film.trickplay")]
    assert len(calls) == 1

    # Simulate destructive overwrite/container change before normal postprocess.
    source.unlink()
    final_output.write_bytes(b"converted")
    result = service.run_result(
        input_path=str(source),
        output_path=str(final_output),
        prepared_source_trickplay=prepared,
    )

    assert len(calls) == 1, "source trickplay must not be attempted a second time"
    assert str(tmp_path / "Film.trickplay") in result.created_paths
    assert result.items[-1]["kind"] == "trickplay"
    assert result.items[-1]["status"] == "created"


def test_dv_runner_prepares_source_trickplay_before_destructive_replace(tmp_path):
    source = tmp_path / "Episode.mkv"
    staging = tmp_path / "__temp_dv_remux__" / "Episode.mp4"
    final = tmp_path / "Episode.mp4"
    source.write_bytes(b"original-video")
    staging.parent.mkdir()

    class Pipeline:
        last_expected_contract = None

        def run(self, **_kwargs):
            staging.write_bytes(b"converted-video" * 200)
            return True

    class OutputManager:
        def build_output_path(self, _input):
            return str(staging)

        def verify_output(self, **_kwargs):
            return True

        def replace_output_if_needed(self, input_path, output_path):
            assert postprocess.prepared
            Path(input_path).unlink()
            Path(output_path).replace(final)
            return True, str(final)

        def cleanup_incomplete(self, *_a):
            pass

    class Postprocess:
        def __init__(self):
            self.prepared = False

        def prepare_source_trickplay(self, *, input_path, output_path):
            assert Path(input_path).exists()
            assert Path(output_path) == final
            self.prepared = True
            root = tmp_path / "Episode.trickplay"
            root.mkdir(exist_ok=True)
            return PostProcessRunResult([str(root)], [{"kind": "trickplay", "status": "created", "path": str(root), "message": ""}])

        def discard_prepared_source_trickplay(self, *_a, **_k):
            pass

        def is_enabled(self):
            return True

        def run_result(self, *, input_path, output_path, prepared_source_trickplay=None):
            assert self.prepared
            assert prepared_source_trickplay is not None
            assert prepared_source_trickplay.created_paths == [str(tmp_path / "Episode.trickplay")]
            assert not Path(input_path).exists()
            root = tmp_path / "Episode.trickplay"
            return PostProcessRunResult([str(root)], [{"kind": "trickplay", "status": "created", "path": str(root), "message": ""}])

    postprocess = Postprocess()
    worker = SimpleNamespace(
        overwrite_original=True,
        container="mp4",
        subtitle_rules={},
        abort_requested=False,
        abort_type=None,
        tools=SimpleNamespace(),
        _postprocess_service=postprocess,
        _sidecar_outputs={},
        _postprocess_outputs={},
        _failure_details={},
        event=_Signal(),
        file_result=_Signal(),
        file_progress=_Signal(),
        log=lambda *_a: None,
    )
    runner = DVRemuxJobRunner(
        worker,
        process_runner=SimpleNamespace(),
        pipeline=Pipeline(),
        output_manager=OutputManager(),
        subtitle_service=SimpleNamespace(
            export_sidecars_result=lambda **_k: SimpleNamespace(
                exported_paths=[], complete=True, failure_summary=lambda: ""
            )
        ),
        prepare_metadata=lambda _p: (
            source.name,
            SimpleNamespace(subtitle_streams=[], analysis_warnings=[]),
            1000,
            None,
        ),
    )

    assert runner.run(str(source)) is True
    assert final.exists()
    assert worker._sidecar_outputs[str(source)] == [str(tmp_path / "Episode.trickplay")]


def test_dv_runner_records_structured_failure_details(tmp_path):
    source = tmp_path / "Broken.mkv"
    source.write_bytes(b"video")
    worker = SimpleNamespace(
        overwrite_original=False,
        container="mkv",
        subtitle_rules={},
        abort_requested=False,
        abort_type=None,
        tools=SimpleNamespace(),
        _postprocess_service=None,
        _sidecar_outputs={},
        _postprocess_outputs={},
        _failure_details={},
        event=_Signal(),
        file_result=_Signal(),
        file_progress=_Signal(),
        log=lambda *_a: None,
    )
    runner = DVRemuxJobRunner(
        worker,
        process_runner=SimpleNamespace(),
        pipeline=SimpleNamespace(run=lambda **_k: False),
        output_manager=SimpleNamespace(
            build_output_path=lambda _p: str(tmp_path / "out.mkv"),
            cleanup_incomplete=lambda *_a: None,
        ),
        subtitle_service=SimpleNamespace(),
        prepare_metadata=lambda _p: (
            source.name,
            SimpleNamespace(subtitle_streams=[], analysis_warnings=[]),
            1000,
            None,
        ),
    )

    assert runner.run(str(source)) is False
    details = worker._failure_details[str(source)]
    assert details["pipeline"] == "dv_remux"
    assert details["container"] == "mkv"
    assert details["strategy"] == "pipeline"
    assert "Pipeline" in details["message"]


def test_postprocess_compat_view_is_derived_and_moved_artifacts_are_consumed():
    state = ConversionSessionState()
    bundle = ConversionArtifactBundle(
        input_path="in.mkv",
        output_path="out.mkv",
        status="✅",
        sidecars=("out.nfo", "out.trickplay"),
        postprocess=({"kind": "nfo", "status": "created"},),
        failure={},
    )
    state.artifacts_by_input["in.mkv"] = bundle
    state.fertig.add("out.mkv")
    state.sidecar_outputs_by_video["out.mkv"] = ["out.nfo", "out.trickplay"]

    assert state.postprocess_outputs_by_input["in.mkv"][0]["kind"] == "nfo"
    assert state.sidecars_for_move()["out.mkv"] == ["out.nfo", "out.trickplay"]

    assert state.consume_moved_output("out.mkv") == ["in.mkv"]
    assert "in.mkv" not in state.artifacts_by_input
    assert "out.mkv" not in state.sidecars_for_move()
    assert "out.mkv" not in state.fertig


def test_async_postprocess_carries_prepared_source_trickplay_with_the_job(tmp_path):
    from dragontools.worker.postprocess_async import AsyncPostProcessCoordinator

    output = tmp_path / "Film.mp4"
    output.write_bytes(b"video")
    trickplay = tmp_path / "Film.trickplay"
    trickplay.mkdir()
    prepared = PostProcessRunResult(
        [str(trickplay)],
        [{"kind": "trickplay", "status": "created", "path": str(trickplay), "message": ""}],
    )
    seen = []

    class Service:
        def run_result(self, *, input_path, output_path, prepared_source_trickplay=None):
            seen.append(prepared_source_trickplay)
            return prepared_source_trickplay or PostProcessRunResult([], [])

    class Results:
        def emit_file_progress(self, *_args):
            pass

        def emit_file_result(self, *_args):
            pass

    sidecars = {}
    details = {}
    coordinator = AsyncPostProcessCoordinator(
        settings=None,
        tools=object(),
        log=lambda *_a: None,
        service_factory=Service,
    )
    assert coordinator.submit(
        input_path="Film.mkv",
        output_path=str(output),
        existing_sidecars=[],
        sidecar_outputs=sidecars,
        postprocess_outputs=details,
        result_service=Results(),
        prepared_source_trickplay=prepared,
    )
    coordinator.wait_for_all()

    assert seen == [prepared]
    assert sidecars["Film.mkv"] == [str(trickplay)]
    assert details["Film.mkv"][0]["kind"] == "trickplay"
