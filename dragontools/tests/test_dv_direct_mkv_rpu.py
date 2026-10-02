from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from dragontools.worker.dv_rpu_service import DVRpuService
from dragontools.worker.dv_video_stage_service import DVVideoStageService
from dragontools.worker.dv_pipeline_context import DVWorkFiles
from dragontools.worker.dv_runtime_models import DVEncoderConfig, DVTempState


def test_rpu_service_builds_mode3_direct_mkv_command(tmp_path):
    commands = []
    service = DVRpuService(dovi_tool_path="dovi_tool", log=lambda *_args: None)
    out = tmp_path / "metadata.rpu"

    def run(command):
        commands.append(command)
        return 0

    assert service.extract_rpu(
        run,
        input_path="movie.mkv",
        output_rpu=out,
        mode=3,
    ) is True
    assert commands == [[
        "dovi_tool", "-m", "3", "extract-rpu", "-i", "movie.mkv", "-o", str(out)
    ]]


def _video_service(tmp_path, rpu_service):
    return DVVideoStageService(
        tools=SimpleNamespace(ffmpeg="ffmpeg", dovi_tool="dovi_tool"),
        encoder_config=DVEncoderConfig(codec="h265", crf=22, preset="medium", options={"encoder": "cpu"}),
        progress_runner=SimpleNamespace(),
        temp_state=DVTempState(),
        hdr10plus_service=SimpleNamespace(),
        rpu_service=rpu_service,
        failure_recovery=SimpleNamespace(),
        log=lambda *_args, **_kwargs: None,
        verbose_log=lambda *_args, **_kwargs: None,
        assert_nonempty_file=lambda path, _label: Path(path).exists() and Path(path).stat().st_size > 0,
        clear_burn_sub_tmp=lambda: None,
    )


def test_non_matroska_keeps_metadata_only_hevc_fallback(tmp_path):
    files = DVWorkFiles.create(tmp_path)
    calls = []

    class Rpu:
        def extract_rpu(self, _run, **kwargs):
            calls.append(kwargs)
            kwargs["output_rpu"].write_bytes(b"rpu")
            return True

    request = SimpleNamespace(
        input_path=str(tmp_path / "movie.mp4"),
        profile_major=8,
        media_info=SimpleNamespace(dv_profile_major=8, dv_profile="8"),
        preserve_dv_hdr10plus_combo=False,
    )
    Path(request.input_path).write_bytes(b"mp4")
    state = SimpleNamespace(request=request, files=files, profile_hevc=None)

    class Runner:
        def run(self, command, **_kwargs):
            files.src_hevc.write_bytes(b"raw-hevc")
            return 0

        def adapter(self, **_kwargs):
            return lambda *_args, **_kwargs: 0

    service = _video_service(tmp_path, Rpu())
    assert service.extract_source_hevc(state, Runner()) is True
    assert files.src_hevc.exists()
    assert service.extract_rpu(state, Runner()) is True
    assert calls[0]["input_hevc"] == files.src_hevc
    assert "input_path" not in calls[0]
    assert calls[0]["mode"] == "2"
