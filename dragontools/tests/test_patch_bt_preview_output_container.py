from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from dragontools.core.models import MediaInfo, VideoStream
from dragontools.core.rules_preview import build_rules_preview
from dragontools.gui import media_info_text_builder as text_builder


def _dv_media() -> MediaInfo:
    return MediaInfo(
        path="dv.mkv",
        audio_streams=[],
        subtitle_streams=[],
        video_streams=[
            VideoStream(
                index=0,
                codec="hevc",
                width=3840,
                height=2160,
                has_dolby_vision=True,
                bit_depth=10,
            )
        ],
        duration_s=120.0,
        dolby_vision=True,
        dv_profile="8",
        dv_profile_major=8,
    )


def _standard_media() -> MediaInfo:
    return MediaInfo(
        path="sdr.mkv",
        audio_streams=[],
        subtitle_streams=[],
        video_streams=[VideoStream(index=0, codec="h264", width=1920, height=1080)],
        duration_s=120.0,
    )


@pytest.mark.parametrize("container", ["mkv", "mp4"])
def test_rules_preview_dv_container_tracks_selected_setting(container: str) -> None:
    preview = build_rules_preview(
        "dv.mkv",
        media_info=_dv_media(),
        codec="h265",
        dv_container=container,
        standard_container="mkv" if container == "mp4" else "mp4",
    )
    assert preview["pipeline"] == "dv"
    assert preview["target_container"] == container


@pytest.mark.parametrize("container", ["mkv", "mp4"])
def test_rules_preview_standard_container_tracks_selected_setting(container: str) -> None:
    preview = build_rules_preview(
        "sdr.mkv",
        media_info=_standard_media(),
        codec="h265",
        standard_container=container,
        dv_container="mp4" if container == "mkv" else "mkv",
    )
    assert preview["pipeline"] == "standard"
    assert preview["target_container"] == container


def test_media_info_text_forwards_both_container_settings(monkeypatch) -> None:
    captured = {}

    def fake_preview(*_args, **kwargs):
        captured.update(kwargs)
        return {
            "pipeline": "dv",
            "target_container": kwargs["dv_container"],
            "target_video": {"resolution": "3840x2160", "autocrop_pending": False},
            "dv_preserved": True,
            "hdr10plus_preserved": False,
            "audio": {},
            "subtitles": {},
            "overrides": {},
            "move": {},
        }

    monkeypatch.setattr(text_builder, "_build_rules_preview", fake_preview)
    mi = SimpleNamespace(
        primary_video=SimpleNamespace(
            width=3840,
            height=2160,
            codec="hevc",
            pix_fmt="yuv420p10le",
            duration_s=120.0,
            frame_count=2880,
            frame_rate="24/1",
            frame_rate_mode="CFR",
            bit_depth=10,
            color_space="bt2020nc",
            color_transfer="smpte2084",
            color_primaries="bt2020",
        ),
        audio_streams=[],
        subtitle_streams=[],
        analysis_source="test",
        color_range="limited",
        is_hdr=True,
        has_hdr10plus=False,
        has_dv=True,
        dolby_vision_profile="8",
        dv_codec_tag="dvhe.08.06",
    )

    text = text_builder.build_media_info_text(
        "dv.mkv",
        mi=mi,
        file_override={},
        planned_target=None,
        subtitle_rules={},
        codec="h265",
        standard_container="mp4",
        dv_container="mkv",
    )

    assert captured["standard_container"] == "mp4"
    assert captured["dv_container"] == "mkv"
    assert "Zielcontainer:  mkv" in text


def test_rule_tester_and_media_info_gui_read_both_output_container_settings() -> None:
    """AST/source contract test for CI environments that deliberately lack PyQt6."""
    root = Path(__file__).parents[1] / "gui"
    files = [
        root / "convert_widget_queue_context_actions.py",
        root / "media_info_dialog.py",
    ]
    for path in files:
        source = path.read_text(encoding="utf-8")
        ast.parse(source)
        assert "SET_KEY_OUTPUT_CONTAINER_STANDARD" in source
        assert "SET_KEY_OUTPUT_CONTAINER_DV" in source
        assert "standard_container=" in source or '"standard_container"' in source
        assert "dv_container=" in source or '"dv_container"' in source
