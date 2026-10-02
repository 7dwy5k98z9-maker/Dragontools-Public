from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from dragontools.worker.dv_pipeline_context import DVWorkFiles
from dragontools.worker.dv_runtime_models import DVEncoderConfig, DVTempState
from dragontools.worker.dv_video_stage_service import DVVideoStageService
from dragontools.worker.frame_count_evidence import FrameCountEvidence


def _encoder_config() -> DVEncoderConfig:
    return DVEncoderConfig(codec="h265", crf=22, preset="medium", options={"encoder": "cpu"})


class _Progress:
    def probe_ms(self, _path):
        return 1_000


class _Runner:
    def run(self, _command, **_kwargs):
        return 0


def _service(tmp_path, *, logs=None):
    logs = logs if logs is not None else []
    return DVVideoStageService(
        tools=SimpleNamespace(ffmpeg="ffmpeg"),
        encoder_config=_encoder_config(),
        progress_runner=_Progress(),
        temp_state=DVTempState(),
        hdr10plus_service=None,
        rpu_service=None,
        failure_recovery=SimpleNamespace(cleanup_tmp_sub=lambda **_kwargs: None),
        log=lambda message, level="info": logs.append((level, message)),
        verbose_log=lambda _message: None,
        assert_nonempty_file=lambda path, _label: Path(path).is_file() and Path(path).stat().st_size > 0,
        clear_burn_sub_tmp=lambda: None,
    )


def _state(tmp_path, *, frame_count=90, profile_major=8):
    source = tmp_path / "movie.mkv"
    source.write_bytes(b"source")
    files = DVWorkFiles.create(tmp_path / "work")
    files.root.mkdir()
    files.enc_hevc.write_bytes(b"broken-encode")
    files.rpu_orig.write_bytes(b"rpu")
    request = SimpleNamespace(
        input_path=str(source),
        output_path=str(tmp_path / "movie_out.mkv"),
        profile_major=profile_major,
        vf_args=["-map", "0:v:0", "-vf", "crop=3840:2076:0:42"],
    )
    return SimpleNamespace(
        request=request,
        files=files,
        effective_vf_args=list(request.vf_args),
        encoded_frame_evidence=FrameCountEvidence.reliable(
            frame_count,
            source="ffmpeg_encode_progress",
            path=files.enc_hevc,
            stage="STEP 4/7 Video-Encoding",
            temporal_mapping="preserved",
        ),
        frame_recovery_applied=False,
        frame_recovery_original_count=None,
        frame_recovery_final_count=None,
        frame_recovery_message="",
    )


def test_early_parity_guard_attempts_partial_repair_before_encode_slot_release(tmp_path, monkeypatch):
    service = _service(tmp_path)
    state = _state(tmp_path, frame_count=90)
    called = []

    def fake_partial(_state, _runner, *, expected_rpu_frames, actual_encode_frames):
        called.append((expected_rpu_frames, actual_encode_frames))
        return True

    monkeypatch.setattr(service, "_attempt_partial_frame_repair", fake_partial)

    assert service.ensure_frame_parity_or_recover(
        state,
        _Runner(),
        probe_rpu_frame_count=lambda _runner, _path: 100,
    ) is True
    assert called == [(100, 90)]
    assert state.encoded_frame_evidence.count == 100
    assert state.encoded_frame_evidence.source == "ffmpeg_partial_repair_validated"


def test_p5_uses_same_partial_repair_policy(tmp_path, monkeypatch):
    service = _service(tmp_path)
    state = _state(tmp_path, frame_count=90, profile_major=5)
    partial_calls = []

    monkeypatch.setattr(
        service,
        "_attempt_partial_frame_repair",
        lambda _state, _runner, *, expected_rpu_frames, actual_encode_frames:
            partial_calls.append((expected_rpu_frames, actual_encode_frames)) or False,
    )

    assert service.ensure_frame_parity_or_recover(
        state, _Runner(), probe_rpu_frame_count=lambda *_args: 100
    ) is False
    assert partial_calls == [(100, 90)]


def test_failed_partial_repair_does_not_start_a_full_reencode(tmp_path, monkeypatch):
    service = _service(tmp_path)
    state = _state(tmp_path, frame_count=90, profile_major=8)
    calls = []
    monkeypatch.setattr(
        service,
        "_attempt_partial_frame_repair",
        lambda *_args, **_kwargs: calls.append("partial") or False,
    )

    assert service.ensure_frame_parity_or_recover(
        state, _Runner(), probe_rpu_frame_count=lambda *_args: 100
    ) is False
    assert calls == ["partial"]
    assert state.files.enc_hevc.read_bytes() == b"broken-encode"
    assert not (state.files.root / "encoded_recovery_original.hevc").exists()


def test_stage_runs_parity_recovery_before_cleanup_and_encode_slot_release(monkeypatch):
    import dragontools.worker.dv_pipeline_stages as module
    from dragontools.worker.dv_pipeline_stages import DVPipelineStages

    events: list[str] = []

    class VideoService:
        def encode_video(self, state, runner):
            events.append("encode")
            return True

        def ensure_frame_parity_or_recover(self, state, runner, *, probe_rpu_frame_count):
            events.append("parity_or_recovery")
            return True

        def cleanup_burn_sub(self, request):
            events.append("cleanup_subtitle")

    monkeypatch.setattr(module, "_video_service", lambda _owner: VideoService())
    stages = object.__new__(DVPipelineStages)
    stages._encode_complete = lambda state: events.append("release_encode_slot") or True
    stages._probe_rpu_frame_count = lambda *_args, **_kwargs: 100
    state = SimpleNamespace(
        request=SimpleNamespace(),
        encode_slot_released=False,
        video_encode_completed=False,
    )

    assert stages._encode_video(state, object()) is True
    assert events == ["encode", "parity_or_recovery", "cleanup_subtitle", "release_encode_slot"]
