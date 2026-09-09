from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


def _burn_sub(*, index: int = 3, codec: str = "subrip"):
    return SimpleNamespace(index=index, codec=codec, language="deu", forced=True)


def _worker():
    logs: list[tuple[str, str]] = []
    return SimpleNamespace(
        tools=SimpleNamespace(ffmpeg="ffmpeg"),
        _burn_sub_tmp=None,
        log=lambda message, level="info": logs.append((level, message)),
        logs=logs,
    )


def test_text_burn_failure_is_fail_closed_and_removes_temp(monkeypatch, tmp_path):
    import dragontools.worker.converter_stream_args as module

    worker = _worker()
    helper = module.ConverterStreamArgsHelper(worker)
    created: list[Path] = []

    real_named_temp = module.tempfile.NamedTemporaryFile

    def tracked_temp(*args, **kwargs):
        handle = real_named_temp(*args, **kwargs)
        created.append(Path(handle.name))
        return handle

    monkeypatch.setattr(module.tempfile, "NamedTemporaryFile", tracked_temp)
    monkeypatch.setattr(
        module,
        "run_tool",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1, stderr="subtitle decode failed", stdout="", aborted=False, timed_out=False
        ),
    )

    with pytest.raises(module.BurnSubtitlePreparationError, match="konnte nicht als SRT"):
        helper.text_burn_vf_args(
            "input.mkv",
            str(tmp_path / "output.mkv"),
            _burn_sub(),
            ["scale=-2:1080"],
        )

    assert worker._burn_sub_tmp is None
    assert created and not created[0].exists()
    assert any("nicht ohne den vorgesehenen Untertitel" in msg for _level, msg in worker.logs)


def test_unknown_planned_burn_codec_is_fail_closed(tmp_path):
    import dragontools.worker.converter_stream_args as module

    worker = _worker()
    helper = module.ConverterStreamArgsHelper(worker)

    with pytest.raises(module.BurnSubtitlePreparationError, match="nicht unterstützten Codec"):
        helper.build_vf_args(
            "input.mkv",
            str(tmp_path / "output.mkv"),
            SimpleNamespace(subtitle_streams=[]),
            _burn_sub(codec="mystery_sub"),
            [],
        )


def test_media_contract_1080p_requires_target_height(monkeypatch):
    import dragontools.worker.media_contract as module

    monkeypatch.setattr(module, "compute_audio_track_plan", lambda **_: [])
    monkeypatch.setattr(
        module,
        "compute_subtitle_plan",
        lambda *_, **__: SimpleNamespace(burn_sub=None, keep_streams=()),
    )
    media = SimpleNamespace(
        audio_streams=[],
        subtitle_streams=[],
        primary_video=SimpleNamespace(codec="h264", bit_depth=8, width=3840, height=2160),
        duration_s=10.0,
        is_hdr=False,
        has_dv=False,
        has_hdrplus=False,
    )

    contract = module.build_expected_media_contract(
        media_info=media,
        file_override={},
        container="mkv",
        pipeline="standard",
        strip_only=False,
        effective_codec="h265",
        effective_preserve_hdrplus=False,
        subtitle_rules={},
        effective_scale_mode="1080p",
        crop_filter=None,
    )

    assert contract.expected_width is None
    assert contract.expected_height == 1080


def test_media_contract_original_with_crop_requires_exact_dimensions(monkeypatch):
    import dragontools.worker.media_contract as module

    monkeypatch.setattr(module, "compute_audio_track_plan", lambda **_: [])
    monkeypatch.setattr(
        module,
        "compute_subtitle_plan",
        lambda *_, **__: SimpleNamespace(burn_sub=None, keep_streams=()),
    )
    media = SimpleNamespace(
        audio_streams=[],
        subtitle_streams=[],
        primary_video=SimpleNamespace(codec="h264", bit_depth=8, width=3840, height=2160),
        duration_s=10.0,
        is_hdr=False,
        has_dv=False,
        has_hdrplus=False,
    )

    contract = module.build_expected_media_contract(
        media_info=media,
        file_override={},
        container="mkv",
        pipeline="standard",
        strip_only=False,
        effective_codec="h265",
        effective_preserve_hdrplus=False,
        subtitle_rules={},
        effective_scale_mode="original",
        crop_filter="crop=3840:1600:0:280",
    )

    assert contract.expected_width == 3840
    assert contract.expected_height == 1600


def test_output_verifier_rejects_wrong_planned_resolution(tmp_path, monkeypatch):
    import dragontools.worker.output_verifier as module
    from dragontools.worker.media_contract import ExpectedMediaContract

    out = tmp_path / "film.mkv"
    out.write_bytes(b"x" * 2048)

    payload = {
        "format": {"format_name": "matroska,webm", "duration": "100"},
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "hevc",
                "pix_fmt": "yuv420p10le",
                "width": 1280,
                "height": 720,
            }
        ],
    }
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=__import__("json").dumps(payload),
            stderr="",
        ),
    )
    contract = ExpectedMediaContract(
        container="mkv",
        video_codec="hevc",
        video_stream_count=1,
        audio_tracks=(),
        subtitle_tracks=(),
        min_video_bit_depth=10,
        expected_width=None,
        expected_height=1080,
    )

    result = module.OutputVerifier(ffprobe_path="ffprobe").verify(
        str(out),
        "mkv",
        expected_duration_ms=100_000,
        expected_contract=contract,
    )

    assert result.ok is False
    assert any("Video-Hoehe abweichend" in message for message in result.messages)
