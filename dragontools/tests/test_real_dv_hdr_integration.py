from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from dragontools.tests.ci_requirements import external_media_environment
from dragontools.worker.dv_mp4box_muxer import DVMP4BoxMuxer
from dragontools.worker.dv_rpu_service import DVRpuService
from dragontools.worker.hdr10plus_bitstream_service import HDR10PlusBitstreamService
from dragontools.worker.tool_runner import run_tool


pytestmark = pytest.mark.dv_hdr_integration

_DOVI_GENERATOR_CONFIG = {
    "cm_version": "V40",
    "length": 10,
    "level6": {
        "max_display_mastering_luminance": 1000,
        "min_display_mastering_luminance": 1,
        "max_content_light_level": 1000,
        "max_frame_average_light_level": 400,
    },
}

# Small valid Profile-B metadata sample derived from hdr10plus_tool's public
# single-frame test fixture. Keeping the fixture local makes CI deterministic
# and does not require downloading copyrighted media.
_HDR10PLUS_SINGLE_FRAME = {
    "JSONInfo": {"HDR10plusProfile": "B", "Version": "1.0"},
    "SceneInfo": [
        {
            "BezierCurveData": {
                "Anchors": [143, 298, 447, 592, 731, 864, 891, 917, 938],
                "KneePointX": 164,
                "KneePointY": 240,
            },
            "LuminanceParameters": {
                "AverageRGB": 263,
                "LuminanceDistributions": {
                    "DistributionIndex": [1, 5, 10, 25, 50, 75, 90, 95, 99],
                    "DistributionValues": [0, 6080, 92, 1, 4, 107, 726, 1784, 5843],
                },
                "MaxScl": [7768, 6589, 6912],
            },
            "NumberOfWindows": 1,
            "TargetedSystemDisplayMaximumLuminance": 400,
            "SceneFrameIndex": 0,
            "SceneId": 0,
            "SequenceFrameIndex": 0,
        }
    ],
    "SceneInfoSummary": {"SceneFirstFrameIndex": [0], "SceneFrameNumbers": [1]},
    "ToolInfo": {"Tool": "hdr10plus_tool", "Version": "1.7.2"},
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: list[str], *, timeout: int = 180):
    result = run_tool(
        command,
        label="DV/HDR integration",
        timeout_s=timeout,
        timeout_mode="absolute",
        worker=None,
        log=lambda *_: None,
    )
    assert result.returncode == 0, (
        f"Command failed ({result.returncode}): {' '.join(command)}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert not result.timed_out
    assert not result.aborted
    return result


def _run_callback(command, allow_error=False, **_kwargs):
    result = run_tool(
        list(command),
        label="DV/HDR integration service",
        timeout_s=180,
        timeout_mode="absolute",
        worker=None,
        log=lambda *_: None,
    )
    if not allow_error:
        assert result.returncode == 0, result.combined_output
    return result.returncode


def _make_hevc(*, ffmpeg: str, target: Path, frames: int) -> None:
    _run([
        ffmpeg,
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-f", "lavfi",
        "-i", f"color=c=black:s=128x72:r=24:d={max(1, frames) / 24:.6f}",
        "-frames:v", str(frames),
        "-c:v", "libx265",
        "-preset", "ultrafast",
        "-x265-params", "log-level=error:repeat-headers=1",
        "-pix_fmt", "yuv420p10le",
        "-an", "-sn", "-dn",
        "-f", "hevc",
        str(target),
    ], timeout=300)
    assert target.is_file() and target.stat().st_size > 1024


def _extract_hevc_from_mp4(*, ffmpeg: str, source: Path, target: Path) -> None:
    _run([
        ffmpeg,
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-i", str(source),
        "-map", "0:v:0",
        "-c:v", "copy",
        "-bsf:v", "hevc_mp4toannexb",
        "-an", "-sn", "-dn",
        "-f", "hevc",
        str(target),
    ])
    assert target.is_file() and target.stat().st_size > 1024


def test_real_dolby_vision_rpu_and_mp4box_roundtrip(tmp_path: Path):
    env = external_media_environment()
    assert not env.missing
    assert env.ffmpeg and env.ffprobe and env.dovi_tool and env.mp4box

    base_hevc = tmp_path / "base.hevc"
    dovi_config = tmp_path / "dovi-generator.json"
    source_rpu = tmp_path / "source.rpu"
    injected_hevc = tmp_path / "injected.hevc"
    injected_rpu = tmp_path / "injected.rpu"
    final_mp4 = tmp_path / "final.mp4"
    final_hevc = tmp_path / "final.hevc"
    final_rpu = tmp_path / "final.rpu"
    logs: list[tuple[str, str]] = []

    _make_hevc(ffmpeg=env.ffmpeg, target=base_hevc, frames=10)
    dovi_config.write_text(json.dumps(_DOVI_GENERATOR_CONFIG), encoding="utf-8")
    _run([env.dovi_tool, "generate", "-j", str(dovi_config), "-o", str(source_rpu)])
    assert source_rpu.is_file() and source_rpu.stat().st_size > 0

    summary = _run([env.dovi_tool, "info", "-s", str(source_rpu)])
    summary_text = f"{summary.stdout}\n{summary.stderr}".casefold()
    assert "frames: 10" in summary_text
    assert "profile: 8" in summary_text

    rpu_service = DVRpuService(
        dovi_tool_path=env.dovi_tool,
        log=lambda message, level: logs.append((level, message)),
    )
    assert rpu_service.inject_rpu(
        _run_callback,
        input_hevc=base_hevc,
        input_rpu=source_rpu,
        output_hevc=injected_hevc,
    )
    assert rpu_service.extract_rpu(
        _run_callback,
        input_hevc=injected_hevc,
        output_rpu=injected_rpu,
    )
    assert _sha256(injected_rpu) == _sha256(source_rpu)

    muxer = DVMP4BoxMuxer(mp4box_path=env.mp4box, audio_track_name=lambda _meta: "")
    assert muxer.mux_final_output(
        _run_callback,
        output_path=str(final_mp4),
        injected_hevc=injected_hevc,
        mux_tracks=[],
    )
    assert final_mp4.is_file() and final_mp4.stat().st_size > 1024

    # Prove that the final MP4 still contains the exact RPU after a real
    # MP4Box container roundtrip.
    _extract_hevc_from_mp4(ffmpeg=env.ffmpeg, source=final_mp4, target=final_hevc)
    assert rpu_service.extract_rpu(
        _run_callback,
        input_hevc=final_hevc,
        output_rpu=final_rpu,
    )
    assert _sha256(final_rpu) == _sha256(source_rpu)

    probe = _run([
        env.ffprobe,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name",
        "-of", "default=nw=1:nk=1",
        str(final_mp4),
    ])
    assert probe.stdout.strip().casefold() in {"hevc", "h265"}


def test_real_hdr10plus_extract_inject_verify_roundtrip(tmp_path: Path):
    env = external_media_environment()
    assert not env.missing
    assert env.ffmpeg and env.hdr10plus_tool

    base_hevc = tmp_path / "hdr-base.hevc"
    source_json = tmp_path / "hdr-source.json"
    injected_hevc = tmp_path / "hdr-injected.hevc"
    verify_json = tmp_path / "hdr-verify.json"
    logs: list[tuple[str, str]] = []

    _make_hevc(ffmpeg=env.ffmpeg, target=base_hevc, frames=1)
    source_json.write_text(
        json.dumps(_HDR10PLUS_SINGLE_FRAME, indent=2),
        encoding="utf-8",
    )

    service = HDR10PlusBitstreamService(
        hdr10plus_tool_path=env.hdr10plus_tool,
        log=lambda message, level: logs.append((level, message)),
    )
    assert service.inject_metadata(
        _run_callback,
        input_hevc=base_hevc,
        metadata_json=source_json,
        output_hevc=injected_hevc,
    )
    assert service.verify_metadata(
        _run_callback,
        source_stream=injected_hevc,
        scratch_json=verify_json,
        expected_json=source_json,
    )
