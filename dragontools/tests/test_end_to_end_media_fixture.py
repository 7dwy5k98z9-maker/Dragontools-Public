from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from dragontools.core.models import AudioStream, MediaInfo, SubtitleStream, VideoStream
from dragontools.worker.media_contract import (
    ExpectedAudioTrack,
    ExpectedMediaContract,
    ExpectedSubtitleTrack,
)
from dragontools.worker.output_verifier import OutputVerifier
from dragontools.worker.subtitle_sidecar_service import SubtitleSidecarService


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")

pytestmark = [
    pytest.mark.media_integration,
    pytest.mark.skipif(
        not FFMPEG or not FFPROBE,
        reason="E2E-Mediafixture benoetigt ffmpeg und ffprobe im PATH",
    ),
]


def _make_tiny_mkv(tmp_path: Path) -> Path:
    subtitle = tmp_path / "fixture.srt"
    subtitle.write_text(
        "1\n00:00:00,100 --> 00:00:00,800\nHallo DragonTools\n",
        encoding="utf-8",
    )
    output = tmp_path / "fixture.mkv"
    command = [
        str(FFMPEG),
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-f", "lavfi",
        "-i", "color=c=black:s=64x64:r=25:d=1",
        "-f", "lavfi",
        "-i", "sine=frequency=1000:sample_rate=48000:duration=1",
        "-i", str(subtitle),
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-map", "2:s:0",
        "-c:v", "mpeg4",
        "-q:v", "5",
        "-c:a", "aac",
        "-ac", "2",
        "-metadata:s:a:0", "language=deu",
        "-c:s", "srt",
        "-metadata:s:s:0", "language=deu",
        str(output),
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert output.is_file() and output.stat().st_size > 1024
    return output


def test_real_ffmpeg_fixture_satisfies_expected_media_contract(tmp_path):
    media = _make_tiny_mkv(tmp_path)
    contract = ExpectedMediaContract(
        container="mkv",
        video_codec="mpeg4",
        video_stream_count=1,
        audio_tracks=(ExpectedAudioTrack(codec="aac", channels=2, language="de"),),
        subtitle_tracks=(
            ExpectedSubtitleTrack(codec="subrip", language="de", forced=False),
        ),
    )

    result = OutputVerifier(ffprobe_path=str(FFPROBE)).verify(
        str(media),
        "mkv",
        expected_duration_ms=1000,
        expected_contract=contract,
    )

    assert result.ok is True, result.messages
    assert result.video_stream_count == 1
    assert result.audio_stream_count == 1
    assert result.subtitle_stream_count == 1
    assert result.format_name in {"matroska,webm", "matroska"}


def test_real_ffmpeg_sidecar_export_reads_original_stream(tmp_path):
    media = _make_tiny_mkv(tmp_path)
    rules = json.loads(
        (PACKAGE_ROOT / "config" / "default_subtitle_rules.json").read_text(encoding="utf-8")
    )
    info = MediaInfo(
        path=str(media),
        audio_streams=[
            AudioStream(
                index=1,
                language="deu",
                forced=False,
                title=None,
                codec="aac",
                channels=2,
            )
        ],
        subtitle_streams=[
            SubtitleStream(
                index=2,
                language="deu",
                forced=False,
                title=None,
                codec="subrip",
            )
        ],
        video_streams=[
            VideoStream(index=0, codec="mpeg4", width=64, height=64)
        ],
        duration_s=1.0,
    )
    logs: list[tuple[str, str]] = []
    service = SubtitleSidecarService(
        ffmpeg_path=str(FFMPEG),
        subtitle_rules=rules,
        log=lambda message, level: logs.append((level, message)),
    )

    result = service.export_sidecars_result(
        input_path=str(media),
        output_base=tmp_path / "exported",
        media_info=info,
    )

    assert result.complete is True, result.failure_summary()
    assert result.planned_stream_indices == (2,)
    assert len(result.exported_paths) == 1
    exported = Path(result.exported_paths[0])
    assert exported.name == "exported.de.srt"
    assert "Hallo DragonTools" in exported.read_text(encoding="utf-8")
