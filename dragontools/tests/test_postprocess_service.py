from __future__ import annotations


def test_prepare_nfo_path_skip_keeps_existing_file(tmp_path):
    from dragontools.worker.postprocess_service import NfoSettings, PostProcessService

    target = tmp_path / "movie.nfo"
    target.write_text("alt", encoding="utf-8")

    service = PostProcessService(settings=None, tools=object(), log=lambda _msg: None)
    prepared, status, should_write = service._prepare_nfo_path(
        target,
        NfoSettings(enabled=True, conflict_mode="skip"),
    )

    assert prepared == target
    assert status == "skipped"
    assert should_write is False
    assert target.read_text(encoding="utf-8") == "alt"


def test_prepare_nfo_path_backup_marks_existing_file_as_saved(tmp_path):
    from dragontools.worker.postprocess_service import NfoSettings, PostProcessService

    target = tmp_path / "movie.nfo"
    target.write_text("alt", encoding="utf-8")

    service = PostProcessService(settings=None, tools=object(), log=lambda _msg: None)
    prepared, status, should_write = service._prepare_nfo_path(
        target,
        NfoSettings(enabled=True, conflict_mode="backup"),
    )

    assert prepared == target
    assert status == "backed_up"
    assert should_write is True
    assert (tmp_path / "movie.nfo.bak").read_text(encoding="utf-8") == "alt"


def test_async_postprocess_coordinator_collects_outputs(tmp_path):
    from dragontools.worker.postprocess_service import (
        AsyncPostProcessCoordinator,
        PostProcessRunResult,
    )

    video = tmp_path / "film.mkv"
    nfo = tmp_path / "film.nfo"
    video.write_text("video", encoding="utf-8")
    nfo.write_text("nfo", encoding="utf-8")
    sidecar_outputs = {"in.mkv": ["film.de.srt"]}
    postprocess_outputs = {}
    events = []

    class FakeService:
        def run_result(self, *, input_path, output_path):
            assert input_path == "in.mkv"
            assert output_path == str(video)
            return PostProcessRunResult(
                [str(nfo)],
                [{"kind": "nfo", "status": "created", "path": str(nfo), "message": ""}],
            )

    class FakeResultService:
        def emit_file_progress(self, input_path, pct):
            events.append(("progress", input_path, pct))

        def emit_file_result(self, input_path, output_path, status):
            events.append(("result", input_path, output_path, status))

    coordinator = AsyncPostProcessCoordinator(
        settings=None,
        tools=object(),
        log=lambda _msg: None,
        service_factory=FakeService,
    )

    assert coordinator.submit(
        input_path="in.mkv",
        output_path=str(video),
        existing_sidecars=sidecar_outputs["in.mkv"],
        sidecar_outputs=sidecar_outputs,
        postprocess_outputs=postprocess_outputs,
        result_service=FakeResultService(),
    )
    coordinator.wait_for_all()

    assert sidecar_outputs["in.mkv"] == ["film.de.srt", str(nfo)]
    assert postprocess_outputs["in.mkv"][0]["kind"] == "nfo"
    assert ("progress", "in.mkv", 100) in events
    assert ("result", "in.mkv", str(video), "✅") in events
