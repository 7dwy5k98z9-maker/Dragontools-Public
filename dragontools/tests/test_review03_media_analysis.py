from __future__ import annotations

from types import SimpleNamespace

import pytest

from dragontools.core.media_analyzer_audio_streams import _build_audio_streams
from dragontools.core.media_analyzer_io import _fp_streams_by_type
from dragontools.core.media_analyzer_metadata import VideoAnalysisMetadata, collect_video_metadata
from dragontools.core.media_analyzer_result import build_media_info
from dragontools.core.media_analyzer_subtitle_streams import _build_subtitle_streams
from dragontools.core.media_analyzer_video_streams import _build_video_streams
from dragontools.core.media_hdr_detection import (
    detect_hdr_from_ffprobe_stream,
    detect_hdr_from_mediainfo_track,
    merge_dolby_vision_info,
    parse_dolby_vision_from_ffprobe_stream,
    parse_dolby_vision_profile,
)
from dragontools.core.models import MediaInfo, VideoStream
from dragontools.worker.media_analysis_service import MediaAnalysisService


def _metadata(*, hdr=False, hdr10plus=False, dv=False) -> VideoAnalysisMetadata:
    return VideoAnalysisMetadata(
        is_hdr=hdr,
        has_hdr10plus=hdr10plus,
        dolby_vision_profile_legacy="8" if dv else None,
        dv_info={
            "dolby_vision": dv,
            "dv_profile": "8" if dv else None,
            "dv_profile_major": 8 if dv else None,
            "dv_codec_tag": "dvhe.08.06" if dv else None,
            "dv_level": "6" if dv else None,
            "dv_format_raw": None,
            "hdr_format_profile_raw": None,
        },
        color_range=None,
        transfer_characteristics=None,
        matrix_coefficients=None,
    )


def test_attached_picture_is_not_a_real_video_stream():
    payload = {
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "mjpeg",
                "disposition": {"attached_pic": 1},
            },
            {
                "index": 1,
                "codec_type": "video",
                "codec_name": "hevc",
                "disposition": {"attached_pic": 0},
            },
        ]
    }

    videos = _fp_streams_by_type(payload, "video")

    assert [stream["index"] for stream in videos] == [1]


def test_bt2020_primaries_without_pq_or_hlg_are_not_hdr():
    mi_hdr, mi_plus, mi_dv = detect_hdr_from_mediainfo_track(
        {
            "Format": "HEVC",
            "BitDepth": "10",
            "colour_primaries": "BT.2020",
            "transfer_characteristics": "BT.709",
        }
    )
    fp_hdr, fp_plus, fp_dv = detect_hdr_from_ffprobe_stream(
        {
            "codec_name": "hevc",
            "pix_fmt": "yuv420p10le",
            "color_primaries": "bt2020",
            "color_transfer": "bt709",
        }
    )

    assert (mi_hdr, mi_plus, mi_dv) == (False, False, None)
    assert (fp_hdr, fp_plus, fp_dv) == (False, False, None)


def test_secondary_dv_stream_does_not_switch_primary_pipeline_flags():
    primary = VideoStream(index=0, codec="hevc", width=1920, height=1080)
    secondary = VideoStream(
        index=1,
        codec="hevc",
        width=1920,
        height=1080,
        hdr_format="dolby_vision",
        has_dolby_vision=True,
        bit_depth=10,
    )
    metadata = collect_video_metadata(
        [primary, secondary],
        [
            {"Format": "HEVC", "transfer_characteristics": "BT.709"},
            {"Format": "HEVC", "HDR_Format": "Dolby Vision, Profile 8, dvhe.08.06"},
        ],
        [
            {"index": 0, "codec_name": "hevc", "color_transfer": "bt709"},
            {
                "index": 1,
                "codec_name": "hevc",
                "side_data_list": [
                    {"side_data_type": "DOVI configuration record", "dv_profile": 8}
                ],
            },
        ],
        [],
    )
    info = MediaInfo(
        path="x.mkv",
        audio_streams=[],
        subtitle_streams=[],
        video_streams=[primary, secondary],
        is_hdr=metadata.is_hdr,
        has_hdr10plus=metadata.has_hdr10plus,
        dolby_vision=metadata.dv_info["dolby_vision"],
    )

    assert metadata.is_hdr is False
    assert metadata.dv_info["dolby_vision"] is False
    assert info.has_dv is False
    assert info.has_hdrplus is False


def test_invalid_mediainfo_dimensions_fall_back_to_ffprobe():
    streams = _build_video_streams(
        [{"Format": "HEVC", "Width": "N/A", "Height": "unknown"}],
        [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "hevc",
                "width": 1920,
                "height": 1080,
            }
        ],
        {},
        [],
    )

    assert streams[0].width == 1920
    assert streams[0].height == 1080


def test_partial_ffprobe_audio_metadata_falls_back_field_by_field():
    streams = _build_audio_streams(
        [
            {
                "Format": "E-AC-3",
                "Channels": "6",
                "Language": "German",
                "Forced": "Yes",
                "Duration": "1441.565",
            }
        ],
        [
            {
                "index": 2,
                "codec_type": "audio",
                "codec_name": "eac3",
                "channels": "N/A",
                "disposition": {},
                "tags": {"language": "und"},
            }
        ],
    )

    assert streams[0].index == 2
    assert streams[0].channels == 6
    assert streams[0].forced is True
    assert streams[0].language == "de"
    assert streams[0].duration_s == pytest.approx(1441.565)


def test_partial_ffprobe_subtitle_forced_falls_back_to_mediainfo():
    streams = _build_subtitle_streams(
        [{"Format": "UTF-8", "Forced": "Yes", "Language": "German"}],
        [
            {
                "index": 4,
                "codec_type": "subtitle",
                "codec_name": "subrip",
                "disposition": {},
                "tags": {"language": "und"},
            }
        ],
    )

    assert streams[0].index == 4
    assert streams[0].forced is True
    assert streams[0].language == "de"


def test_ffprobe_subtitle_duration_is_always_seconds_even_above_10000():
    streams = _build_subtitle_streams(
        [{}],
        [
            {
                "index": 3,
                "codec_type": "subtitle",
                "codec_name": "subrip",
                "duration": "14400.0",
            }
        ],
    )

    assert streams[0].duration_s == pytest.approx(14400.0)


def test_general_mediainfo_duration_is_parsed_before_source_duration():
    info = build_media_info(
        path="missing.mkv",
        mi_general={"Duration": "1441.565", "FileSize": "N/A"},
        ffprobe_json={"format": {"size": "12345"}, "streams": []},
        video_streams=[],
        audio_streams=[],
        subtitle_streams=[],
        metadata=_metadata(),
        analysis_source="MediaInfo.exe",
        analysis_warnings=[],
    )

    assert info.duration_s == pytest.approx(1441.565)
    assert info.size_bytes == 12345


def test_ffprobe_only_equal_rates_infer_cfr():
    streams = _build_video_streams(
        [],
        [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "hevc",
                "avg_frame_rate": "24000/1001",
                "r_frame_rate": "24000/1001",
            }
        ],
        {},
        [],
    )

    assert streams[0].frame_rate == "24000/1001"
    assert streams[0].frame_rate_mode == "CFR"


def test_dv_merge_does_not_keep_codec_tag_from_conflicting_profile():
    mi = parse_dolby_vision_profile(
        {"HDR_Format": "Dolby Vision, Profile 7, dvhe.07.06"}
    )
    fp = parse_dolby_vision_from_ffprobe_stream(
        {
            "side_data_list": [
                {"side_data_type": "DOVI configuration record", "dv_profile": 8, "dv_level": 6}
            ]
        }
    )

    merged = merge_dolby_vision_info(mi, fp, [])

    assert merged["dv_profile_major"] == 8
    assert merged["dv_codec_tag"] is None


def test_arbitrary_title_tag_cannot_fake_dolby_vision():
    parsed = parse_dolby_vision_from_ffprobe_stream(
        {
            "codec_name": "hevc",
            "codec_tag_string": "hev1",
            "tags": {"title": "Dolby Vision Documentary"},
        }
    )

    assert parsed["dolby_vision"] is False


def test_mediainfo_streamorder_is_not_fabricated_as_ffmpeg_index():
    warnings: list[str] = []
    audio = _build_audio_streams(
        [{"Format": "AAC", "StreamOrder": "7", "Language": "German"}],
        [],
        warnings,
    )
    subtitles = _build_subtitle_streams(
        [{"Format": "UTF-8", "StreamOrder": "9", "Language": "German"}],
        [],
        warnings,
    )

    assert audio[0].index == -1
    assert subtitles[0].index == -1
    assert any("MediaInfo StreamOrder" in warning for warning in warnings)


def test_build_media_info_marks_untrusted_stream_indices():
    audio = _build_audio_streams([{"Format": "AAC", "StreamOrder": "1"}], [], [])
    info = build_media_info(
        path="missing.mkv",
        mi_general={},
        ffprobe_json={},
        video_streams=[],
        audio_streams=audio,
        subtitle_streams=[],
        metadata=_metadata(),
        analysis_source="MediaInfo.exe",
        analysis_warnings=[],
    )

    assert info.ffmpeg_stream_indices_trusted is False


def test_conversion_analysis_fails_closed_for_untrusted_stream_indices(monkeypatch):
    from dragontools.worker import media_analysis_service as module

    media = SimpleNamespace(
        ffmpeg_stream_indices_trusted=False,
        analysis_warnings=["unsafe mapping"],
    )
    monkeypatch.setattr(module, "analyze_media", lambda *_args, **_kwargs: media)
    log_messages: list[tuple[str, str]] = []
    service = MediaAnalysisService(
        tools=SimpleNamespace(),
        probe_duration_ms=lambda _path: 1000,
        log=lambda message, level: log_messages.append((message, level)),
    )

    with pytest.raises(RuntimeError, match="ffprobe.*Streamindizes"):
        service.analyze("source.mkv")

    assert log_messages


def test_media_contract_carries_expected_normalized_dv_profile(monkeypatch):
    import dragontools.worker.media_contract as module

    media = SimpleNamespace(
        audio_streams=[],
        subtitle_streams=[],
        primary_video=SimpleNamespace(codec="hevc", bit_depth=10, width=1920, height=1080),
        duration_s=100.0,
        is_hdr=True,
        has_dv=True,
        has_hdrplus=False,
        has_hdr10plus=False,
        dv_profile_major=5,
        dv_profile="5",
        dolby_vision_profile="5",
        transfer_characteristics="smpte2084",
    )
    monkeypatch.setattr(module, "compute_audio_track_plan", lambda **_: [])
    monkeypatch.setattr(
        module,
        "compute_subtitle_plan",
        lambda *_, **__: SimpleNamespace(burn_sub=None, keep_streams=()),
    )

    contract = module.build_expected_media_contract(
        media_info=media,
        file_override={},
        container="mkv",
        pipeline="dv",
        strip_only=False,
        effective_codec="h265",
        effective_preserve_hdrplus=False,
        subtitle_rules={},
    )

    assert contract.require_dolby_vision is True
    assert contract.expected_dolby_vision_profile == 8


def test_malformed_probe_json_roots_fail_safely(monkeypatch):
    from dragontools.core import media_analyzer_io as module

    monkeypatch.setattr(
        module,
        "_run_tool",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="[]"),
    )

    payload, warnings = module._run_ffprobe_json(
        "movie.mkv",
        SimpleNamespace(ffprobe="ffprobe"),
    )

    assert payload == {}
    assert any("keinen Objekt-Root" in warning for warning in warnings)


def test_malformed_nested_probe_payloads_do_not_crash_stream_parsing():
    from dragontools.core.media_analyzer_io import _mi_tracks

    mi_tracks = _mi_tracks(
        {"media": {"track": [None, "broken", {"@type": "Video", "Format": "HEVC"}]}}
    )
    fp_videos = _fp_streams_by_type(
        {
            "streams": [
                None,
                "broken",
                {
                    "index": 5,
                    "codec_type": "video",
                    "codec_name": "hevc",
                    "disposition": {"attached_pic": 0},
                },
            ]
        },
        "video",
    )

    assert mi_tracks == [{"@type": "Video", "Format": "HEVC"}]
    assert [stream["index"] for stream in fp_videos] == [5]


def test_malformed_hdr_side_data_is_ignored_instead_of_crashing():
    from dragontools.core.media_hdr_detection import detect_hdr10plus_from_ffprobe_frames

    dv = parse_dolby_vision_from_ffprobe_stream(
        {"codec_name": "hevc", "tags": "broken", "side_data_list": [None, "bad"]}
    )
    hdr, hdr10plus, profile = detect_hdr_from_ffprobe_stream(
        {"codec_name": "hevc", "side_data_list": [None, "bad"]}
    )

    assert dv["dolby_vision"] is False
    assert (hdr, hdr10plus, profile) == (False, False, None)
    assert detect_hdr10plus_from_ffprobe_frames(
        {"frames": [None, "bad", {"side_data_list": [None, "bad"]}]}
    ) is False


def test_dynamic_hdr_frame_probe_selects_primary_by_global_ffprobe_index(monkeypatch):
    from dragontools.core import media_analyzer_io as module

    commands: list[list[str]] = []

    def fake_run_tool(command, **_kwargs):
        commands.append(list(command))
        return SimpleNamespace(stdout='{"frames": []}')

    monkeypatch.setattr(module, "_run_tool", fake_run_tool)

    payload, warnings = module._run_ffprobe_dynamic_hdr_frames(
        "movie with cover.mkv",
        SimpleNamespace(ffprobe="ffprobe"),
        stream_index=3,
    )

    assert payload == {"frames": []}
    assert warnings == []
    selector_pos = commands[0].index("-select_streams")
    assert commands[0][selector_pos + 1] == "3"


def test_dynamic_hdr_frame_probe_fails_closed_without_trusted_stream_index(monkeypatch):
    from dragontools.core import media_analyzer_dynamic_hdr as module

    called = False

    def should_not_run(*_args, **_kwargs):
        nonlocal called
        called = True
        return {}, []

    monkeypatch.setattr(module, "_run_ffprobe_dynamic_hdr_frames", should_not_run)
    primary = VideoStream(
        index=-1,
        codec="hevc",
        width=1920,
        height=1080,
        bit_depth=10,
        hdr_format="hdr10",
        color_transfer="smpte2084",
    )
    warnings: list[str] = []

    applied = module.apply_hdr10plus_frame_fallback(
        "movie.mkv", SimpleNamespace(ffprobe="ffprobe"), [primary], warnings
    )

    assert applied is False
    assert called is False
    assert any("kein verlässlicher ffprobe-Streamindex" in warning for warning in warnings)


def test_malformed_nested_tags_disposition_and_language_fail_softly():
    audio = _build_audio_streams(
        [{"Format": "AAC", "Language": 123, "Forced": "Yes", "Channels": "2"}],
        [
            {
                "index": 2,
                "codec_type": "audio",
                "codec_name": "aac",
                "tags": "broken",
                "disposition": "broken",
                "channels": 2,
            }
        ],
    )
    subtitles = _build_subtitle_streams(
        [{"Format": "UTF-8", "Language": 456, "Forced": "Yes"}],
        [
            {
                "index": 3,
                "codec_type": "subtitle",
                "codec_name": "subrip",
                "tags": "broken",
                "disposition": "broken",
            }
        ],
    )
    videos = _fp_streams_by_type(
        {
            "streams": [
                {
                    "index": 1,
                    "codec_type": "video",
                    "codec_name": "hevc",
                    "disposition": "broken",
                }
            ]
        },
        "video",
    )

    assert audio[0].language == "123"
    assert audio[0].forced is True
    assert subtitles[0].language == "456"
    assert subtitles[0].forced is True
    assert [stream["index"] for stream in videos] == [1]


def test_negative_video_framecount_and_bitrate_do_not_override_valid_ffprobe_values():
    streams = _build_video_streams(
        [
            {
                "Format": "HEVC",
                "FrameCount": "-1",
                "BitRate": "-1",
                "Width": "1920",
                "Height": "1080",
            }
        ],
        [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "hevc",
                "nb_frames": "2400",
                "bit_rate": "2500000",
                "width": 1920,
                "height": 1080,
            }
        ],
        {},
        [],
    )

    assert streams[0].frame_count == 2400
    assert streams[0].bitrate == 2_500_000


def test_source_duration_ignores_malformed_nested_streams_and_format():
    from dragontools.core.media_duration import source_duration

    duration = source_duration(
        {
            "streams": [None, "bad", {"codec_type": "audio", "duration": "42.5", "tags": "bad"}],
            "format": "bad",
        },
        video_streams=[],
        audio_streams=[],
        container_duration=None,
    )

    assert duration == pytest.approx(42.5)


def test_build_media_info_tolerates_malformed_ffprobe_format_object():
    info = build_media_info(
        path="missing.mkv",
        mi_general={},
        ffprobe_json={"format": "broken", "streams": []},
        video_streams=[],
        audio_streams=[],
        subtitle_streams=[],
        metadata=_metadata(),
        analysis_source="FFmpeg",
        analysis_warnings=[],
    )

    assert info.duration_s == 0.0
    assert info.size_bytes == 0


def test_mediainfo_details_accepts_single_track_object():
    from dragontools.core.mediainfo_details import build_mediainfo_display_details

    details = build_mediainfo_display_details(
        "missing.mkv",
        payload={"media": {"track": {"@type": "General", "Format": "Matroska"}}},
    )

    assert dict(details.overview_rows)["Container"] == "Matroska"


def test_profile_assistant_rejects_unknown_codec_instead_of_silently_using_h265():
    from dragontools.core.codec_profile_assistant import assistant_profiles_for_codec

    assert assistant_profiles_for_codec("corrupt-codec") == []
    assert all(item.profile["codec"] == "h265" for item in assistant_profiles_for_codec("hevc"))


def test_track_revalidation_rejects_malformed_ffprobe_payload_cleanly(monkeypatch):
    from dragontools.worker import media_stream_metadata_guard as module

    monkeypatch.setattr(
        module,
        "run_tool",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            aborted=False,
            stdout='["not-an-object"]',
        ),
    )
    issue = SimpleNamespace(
        path="movie.mkv",
        stream_type="audio",
        stream_ordinal=1,
        stream_index=2,
        codec="aac",
        language="de",
        track_title="Deutsch",
        forced=False,
        channels=2,
    )

    with pytest.raises(ValueError, match="ungültige Trackdaten"):
        module._validate_track(issue, SimpleNamespace(ffprobe="ffprobe"), None)


def test_probe_placeholder_language_negative_bitrate_and_string_flags_fall_back_safely():
    audio = _build_audio_streams(
        [{"Format": "AAC", "Language": "German", "BitRate": "256000", "Forced": "No"}],
        [
            {
                "index": 2,
                "codec_type": "audio",
                "codec_name": "aac",
                "bit_rate": "-1",
                "tags": {"language": "N/A"},
                "disposition": {"forced": "0"},
            }
        ],
    )
    subs = _build_subtitle_streams(
        [{"Format": "UTF-8", "Language": "German", "Forced": "No"}],
        [
            {
                "index": 3,
                "codec_type": "subtitle",
                "codec_name": "subrip",
                "tags": {"language": "unknown"},
                "disposition": {"forced": "0"},
            }
        ],
    )
    videos = _fp_streams_by_type(
        {
            "streams": [
                {
                    "index": 0,
                    "codec_type": "video",
                    "codec_name": "hevc",
                    "disposition": {"attached_pic": "0"},
                }
            ]
        },
        "video",
    )

    assert audio[0].language == "de"
    assert audio[0].bitrate == 256000
    assert audio[0].forced is False
    assert subs[0].language == "de"
    assert subs[0].forced is False
    assert len(videos) == 1


def test_non_string_probe_type_fields_are_ignored_without_crashing():
    from dragontools.core.media_analyzer_io import _mi_audio_tracks, _mi_video_tracks

    mi = {
        "media": {
            "track": [
                {"@type": 123, "Format": "broken"},
                {"@type": "Video", "Format": "HEVC"},
                {"@type": "Audio", "Format": 456},
            ]
        }
    }
    fp = {
        "streams": [
            {"index": 0, "codec_type": 123},
            {"index": 1, "codec_type": "video", "disposition": {}},
        ]
    }

    assert len(_mi_video_tracks(mi)) == 1
    assert len(_mi_audio_tracks(mi)) == 1
    assert _fp_streams_by_type(fp, "video")[0]["index"] == 1


def test_invalid_mediainfo_frame_rate_mode_does_not_block_ffprobe_inference():
    streams = _build_video_streams(
        [{"Format": "HEVC", "FrameRate_Mode": "N/A"}],
        [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "hevc",
                "avg_frame_rate": "25/1",
                "r_frame_rate": "25/1",
            }
        ],
        {},
        [],
    )

    assert streams[0].frame_rate_mode == "CFR"


def test_fractional_ffprobe_stream_index_is_never_truncated_into_another_track():
    warnings: list[str] = []
    audio = _build_audio_streams(
        [],
        [{"index": "2.9", "codec_type": "audio", "codec_name": "aac"}],
        warnings,
    )

    assert audio[0].index == -1
    assert any("Stream-ID" in warning for warning in warnings)


def test_unequal_ffprobe_rate_fields_do_not_invent_vfr():
    streams = _build_video_streams(
        [],
        [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "hevc",
                "avg_frame_rate": "25/1",
                "r_frame_rate": "50/1",
            }
        ],
        {},
        [],
    )

    assert streams[0].frame_rate_mode is None


def test_source_duration_uses_audio_track_that_agrees_with_container_for_broken_video():
    from dragontools.core.media_duration import source_duration

    duration = source_duration(
        {
            "format": {"duration": "100.0"},
            "streams": [
                {"index": 0, "codec_type": "video", "duration": "10000.0"},
                {"index": 1, "codec_type": "audio", "duration": "30.0"},
                {"index": 2, "codec_type": "audio", "duration": "100.0"},
            ],
        }
    )

    assert duration == pytest.approx(100.0)


def test_source_duration_uses_longest_audio_when_video_and_container_are_missing():
    from dragontools.core.media_duration import source_duration

    duration = source_duration(
        {
            "streams": [
                {"index": 1, "codec_type": "audio", "duration": "30.0"},
                {"index": 2, "codec_type": "audio", "duration": "100.0"},
            ]
        }
    )

    assert duration == pytest.approx(100.0)


def test_non_string_ffprobe_pix_fmt_is_treated_as_unknown_not_crash():
    streams = _build_video_streams(
        [{}],
        [{"index": 0, "codec_type": "video", "codec_name": "hevc", "pix_fmt": 123}],
        {},
        [],
    )

    assert streams[0].bit_depth is None


def test_secondary_hdr10plus_stream_does_not_suppress_primary_frame_probe():
    from dragontools.core.media_analyzer_dynamic_hdr import needs_hdr10plus_frame_probe

    primary = VideoStream(
        index=0,
        codec="hevc",
        width=1920,
        height=1080,
        bit_depth=10,
        hdr_format="hdr10",
        color_transfer="smpte2084",
    )
    secondary = VideoStream(
        index=1,
        codec="hevc",
        width=1920,
        height=1080,
        bit_depth=10,
        hdr_format="hdr10plus",
        has_hdr10plus=True,
        color_transfer="smpte2084",
    )

    assert needs_hdr10plus_frame_probe([primary, secondary]) is True
