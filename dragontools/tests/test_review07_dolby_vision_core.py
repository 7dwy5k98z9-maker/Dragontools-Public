from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from dragontools.core.models import TargetCodec
import dragontools.worker.dv5_encode_fallback as dv5_fallback
from dragontools.worker.dv_command_runner import DVCommandRunner
from dragontools.worker.dv_crop_reconcile import replace_crop_in_vf_args
from dragontools.worker.dv_dynamic_metadata_service import DVDynamicMetadataService
from dragontools.worker.dv_encode_command import build_dv_encode_command
from dragontools.worker.dv_final_metadata_verifier import DVFinalMetadataVerifier
from dragontools.worker.dv_pipeline_context import DVRunRequest, DVWorkFiles
from dragontools.worker.dv_pipeline_runtime import DVPreflightService
from dragontools.worker.dv_runtime_models import DVEncoderConfig, DVTempState
from dragontools.worker.dv_video_stage_service import DVVideoStageService
from dragontools.worker.frame_count_evidence import FrameCountEvidence
from dragontools.worker.tool_runner import ToolRunResult


def _encoder() -> DVEncoderConfig:
    return DVEncoderConfig(codec=TargetCodec.H265, crf=22, preset="medium", options={"encoder": "cpu"})


def _request(tmp_path: Path, *, profile=8, container="mkv", media_info=None) -> DVRunRequest:
    if media_info is None:
        video = SimpleNamespace(index=2, codec="hevc", width=3840, height=2160)
        media_info = SimpleNamespace(
            dv_profile_major=profile,
            primary_video=video,
            video_streams=[video],
            ffmpeg_stream_indices_trusted=True,
        )
    return DVRunRequest.create(
        input_path=str(tmp_path / "input.mkv"),
        output_path=str(tmp_path / f"output.{container or 'mkv'}"),
        media_info=media_info,
        vf_args=[], audio_args=[], audio_input_args=[], sn=[], crop=None, override={},
        preserve_hdrplus=False, container=container,
    )


def _preflight() -> DVPreflightService:
    return DVPreflightService(
        tools=SimpleNamespace(ffmpeg="ffmpeg"),
        log=lambda *_a, **_k: None,
        verbose_log=lambda *_a, **_k: None,
        libplacebo_available=lambda: True,
    )


@pytest.mark.parametrize("profile", [None, 4, 9, 10, 20])
def test_hevc_dv_preflight_rejects_unsupported_profiles(tmp_path, profile):
    video = SimpleNamespace(index=0, codec="hevc")
    media = SimpleNamespace(
        dv_profile_major=profile, primary_video=video, video_streams=[video],
        ffmpeg_stream_indices_trusted=True,
    )
    req = _request(tmp_path, profile=profile, media_info=media)
    ok, reason, _stage = _preflight().validate(encoder_config=_encoder(), request=req)
    assert ok is False
    assert "Profil" in reason


def test_dv_request_does_not_silently_turn_empty_container_into_mp4(tmp_path):
    video = SimpleNamespace(index=0, codec="hevc")
    req = DVRunRequest.create(
        input_path="in.mkv", output_path="out.mp4",
        media_info=SimpleNamespace(dv_profile_major=8, primary_video=video, video_streams=[video]),
        vf_args=[], audio_args=[], audio_input_args=[], sn=[], crop=None, override={},
        preserve_hdrplus=False, container=None,
    )
    assert req.container == ""
    ok, reason, _ = _preflight().validate(encoder_config=_encoder(), request=req)
    assert not ok and "container" in reason.lower()


def test_dv_preflight_rejects_untrusted_or_non_hevc_primary_stream(tmp_path):
    video = SimpleNamespace(index=3, codec="av1")
    media = SimpleNamespace(dv_profile_major=8, primary_video=video, video_streams=[video], ffmpeg_stream_indices_trusted=True)
    ok, reason, _ = _preflight().validate(encoder_config=_encoder(), request=_request(tmp_path, media_info=media))
    assert not ok and "HEVC" in reason

    video.codec = "hevc"
    media.ffmpeg_stream_indices_trusted = False
    ok, reason, _ = _preflight().validate(encoder_config=_encoder(), request=_request(tmp_path, media_info=media))
    assert not ok and "Streamindizes" in reason


def test_encode_command_pins_global_ffmpeg_stream_index_in_map_and_filter_graph(tmp_path):
    plan = build_dv_encode_command(
        ffmpeg_path="ffmpeg", encoder_config=_encoder(), input_path="input.mkv",
        output_hevc=tmp_path / "out.hevc",
        vf_args=["-filter_complex", "[0:v:0]scale=1920:1080[vout]", "-map", "[vout]"],
        profile_major=8, source_stream_index=3,
    )
    graph = plan.command[plan.command.index("-filter_complex") + 1]
    assert "[0:3]" in graph
    assert "[0:v:0]" not in graph

    plan2 = build_dv_encode_command(
        ffmpeg_path="ffmpeg", encoder_config=_encoder(), input_path="input.mkv",
        output_hevc=tmp_path / "out2.hevc", vf_args=["-map", "0:v:0"],
        profile_major=8, source_stream_index=4,
    )
    assert plan2.command[plan2.command.index("-map") + 1] == "0:4"


def _video_service(tmp_path, *, rpu_service, temp_state=None):
    return DVVideoStageService(
        tools=SimpleNamespace(ffmpeg="ffmpeg", dovi_tool="dovi_tool", mkvmerge="mkvmerge"),
        encoder_config=_encoder(), progress_runner=SimpleNamespace(),
        temp_state=temp_state or DVTempState(), hdr10plus_service=SimpleNamespace(),
        rpu_service=rpu_service, failure_recovery=SimpleNamespace(),
        log=lambda *_a, **_k: None, verbose_log=lambda *_a, **_k: None,
        assert_nonempty_file=lambda p, _l: Path(p).exists() and Path(p).stat().st_size > 0,
        clear_burn_sub_tmp=lambda: None,
    )


def test_direct_mkv_rpu_maps_primary_ffmpeg_stream_to_matroska_track_number(tmp_path):
    files = DVWorkFiles.create(tmp_path)
    video0 = SimpleNamespace(index=1, codec="hevc")
    video1 = SimpleNamespace(index=3, codec="hevc")
    req = SimpleNamespace(
        input_path=str(tmp_path / "multi.mkv"), profile_major=8,
        media_info=SimpleNamespace(primary_video=video1, video_streams=[video0, video1]),
        preserve_dv_hdr10plus_combo=False,
    )
    state = SimpleNamespace(request=req, files=files)
    seen = {}

    class Rpu:
        def extract_rpu(self, _run, **kwargs):
            seen.update(kwargs)
            kwargs["output_rpu"].write_bytes(b"rpu")
            return True

    class Runner:
        def run(self, command, **_kwargs):
            assert command[:2] == ["mkvmerge", "-J"]
            payload = {
                "tracks": [
                    {"id": 0, "type": "video", "properties": {"number": 2}},
                    {"id": 1, "type": "audio", "properties": {"number": 4}},
                    {"id": 2, "type": "video", "properties": {"number": 7}},
                ]
            }
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
        def adapter(self, **_kwargs):
            return lambda *_a, **_k: 0

    service = _video_service(tmp_path, rpu_service=Rpu())
    assert service.extract_rpu(state, Runner()) is True
    assert seen["input_path"] == req.input_path
    assert seen["track_number"] == 7


def test_non_matroska_source_hevc_maps_global_primary_stream(tmp_path):
    files = DVWorkFiles.create(tmp_path)
    video = SimpleNamespace(index=5, codec="hevc")
    req = SimpleNamespace(
        input_path=str(tmp_path / "input.mp4"), profile_major=8,
        media_info=SimpleNamespace(primary_video=video, video_streams=[video]),
        preserve_dv_hdr10plus_combo=False,
    )
    state = SimpleNamespace(request=req, files=files)
    seen = {}
    class Runner:
        def run(self, command, **_kwargs):
            seen["command"] = command
            files.src_hevc.write_bytes(b"hevc")
            return 0
    assert _video_service(tmp_path, rpu_service=SimpleNamespace()).extract_source_hevc(state, Runner())
    cmd = seen["command"]
    assert cmd[cmd.index("-map") + 1] == "0:5"


def test_filter_complex_crop_removal_uses_noop_instead_of_invalid_empty_filter():
    args = ["-filter_complex", "[0:v:0]crop=1920:800:0:140,subtitles=x.ass[vout]", "-map", "[vout]"]
    result = replace_crop_in_vf_args(args, "crop=1920:800:0:140", None)
    graph = result[result.index("-filter_complex") + 1]
    assert "[0:v:0]null,subtitles=" in graph
    assert "[0:v:0],subtitles=" not in graph


def test_rpu_frame_parity_fails_closed_without_reliable_hevc_count(tmp_path):
    temp = DVTempState()
    service = DVDynamicMetadataService(
        tools=SimpleNamespace(ffprobe="ffprobe", dovi_tool="dovi_tool"), temp_state=temp,
        audio_mux_service=None, rpu_service=None, hdr10plus_service=None, generator_client=None,
        level5_editor=None, failure_recovery=None, log=lambda *_a, **_k: None,
        verbose_log=lambda *_a, **_k: None, assert_nonempty_file=lambda *_a, **_k: True,
    )
    estimate = FrameCountEvidence.estimated(100, source="duration", path=tmp_path / "x.hevc", stage="preflight")
    ok = service.validate_rpu_frame_parity(
        SimpleNamespace(), rpu_path=tmp_path / "x.rpu", hevc_path=tmp_path / "x.hevc",
        frame_evidence=estimate, probe_rpu_frame_count=lambda *_a: 100,
        probe_hevc_frame_count=lambda *_a: None,
    )
    assert ok is False
    assert "nicht sicher nachgewiesen" in temp.failure_reason


def test_optional_dv_probe_does_not_erase_existing_failure(monkeypatch):
    import dragontools.worker.dv_command_runner as module
    temp = DVTempState(failure_reason="kritischer Fehler", failure_stage="STEP 4", stderr="original")
    monkeypatch.setattr(module, "run_tool", lambda *a, **k: ToolRunResult(command=list(a[0]), returncode=2, stderr="probe failed"))
    runner = DVCommandRunner(log=lambda *_a: None, verbose_log=lambda *_a: None, no_window_kwargs=lambda: {}, temp_state=temp)
    assert runner.run(["dovi_tool", "info", "x.rpu"], allow_error=True) == 2
    assert temp.failure_reason == "kritischer Fehler"
    assert temp.failure_stage == "STEP 4"
    assert temp.stderr == "original"


def _final_verifier(tmp_path, temp=None):
    return DVFinalMetadataVerifier(
        tools=SimpleNamespace(ffmpeg="ffmpeg", dovi_tool="dovi_tool"), temp_state=temp or DVTempState(),
        rpu_service=SimpleNamespace(), hdr10plus_service=SimpleNamespace(),
        log=lambda *_a, **_k: None, verbose_log=lambda *_a, **_k: None,
        assert_nonempty_file=lambda *_a, **_k: True,
    )


def test_final_dv_signalling_always_requires_bitstream_rpu_proof(tmp_path):
    verifier = _final_verifier(tmp_path)
    req = SimpleNamespace(output_path=str(tmp_path / "out.mkv"), container="mkv", profile_major=8,
                          preserve_dv_hdr10plus_combo=False, generate_hdr10plus=False)
    state = SimpleNamespace(request=req, effective_crop=None, verified_dolby_vision=False, verified_hdr10plus=False)
    inspection = SimpleNamespace(conclusive=True, dolby_vision=True, dolby_vision_profile="8.1", hdr10plus=False, warnings=())
    seen = {}
    def fallback(_state, _runner, *, verify_dv, verify_hdr10plus):
        seen.update(dv=verify_dv, hdr=verify_hdr10plus)
        return True
    assert verifier.verify(state, SimpleNamespace(), inspect_dynamic_hdr=lambda *_a: inspection, verify_fallback=fallback)
    assert seen == {"dv": True, "hdr": False}


def test_final_dv_explicit_wrong_profile_is_rejected_before_success(tmp_path):
    temp = DVTempState()
    verifier = _final_verifier(tmp_path, temp)
    req = SimpleNamespace(output_path=str(tmp_path / "out.mkv"), container="mkv", profile_major=7,
                          preserve_dv_hdr10plus_combo=False, generate_hdr10plus=False)
    state = SimpleNamespace(request=req, effective_crop=None, verified_dolby_vision=False, verified_hdr10plus=False)
    inspection = SimpleNamespace(conclusive=True, dolby_vision=True, dolby_vision_profile="7.6", hdr10plus=False, warnings=())
    called = []
    ok = verifier.verify(state, SimpleNamespace(), inspect_dynamic_hdr=lambda *_a: inspection,
                         verify_fallback=lambda *_a, **_k: called.append(True) or True)
    assert ok is False
    assert called == []
    assert "erwartet P8" in temp.failure_reason


def test_dv5_override_lookup_uses_canonical_windows_path_and_deepcopy():
    original = {r"C:\\Media\\Film.mkv": {"audio": {"mode": "copy"}}}
    found = dv5_fallback._override_for_path(original, "c:/media/film.mkv")
    assert found == {"audio": {"mode": "copy"}}
    found["audio"]["mode"] = "aac"
    assert original[r"C:\\Media\\Film.mkv"]["audio"]["mode"] == "copy"
