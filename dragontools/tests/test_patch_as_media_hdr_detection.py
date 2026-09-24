from __future__ import annotations

from types import SimpleNamespace

from dragontools.core.media_analyzer_video_streams import _hdr_state
from dragontools.core.media_hdr_detection import (
    detect_hdr_from_ffprobe_stream,
    detect_hdr_from_mediainfo_track,
    merge_dolby_vision_info,
    parse_dolby_vision_from_ffprobe_stream,
    parse_dolby_vision_profile,
    validate_hdr_flags,
)


def test_mediainfo_erkennt_hdr10plus_profile_a_allein_an_st2094_app4():
    track = {
        "Format": "HEVC",
        "Format_Profile": "Main 10",
        "BitDepth": "10",
        "HDR_Format": "SMPTE ST 2094 App 4",
        "HDR_Format_Version": "1",
        "HDR_Format_Commercial": "SMPTE ST 2094 App 4",
        "colour_primaries": "BT.2020",
        "transfer_characteristics": "PQ",
    }

    is_hdr, hdr10plus, dv_profile = detect_hdr_from_mediainfo_track(track)

    assert is_hdr is True
    assert hdr10plus is True
    assert dv_profile is None


def test_mediainfo_erkennt_dv81_und_hdr10plus_kombination():
    track = {
        "HDR_Format": (
            "Dolby Vision, Version 1.0, Profile 8.1, dvhe.08.06, BL+RPU / "
            "SMPTE ST 2094 App 4"
        ),
        "HDR_Format_Profile": "dvhe.08.06",
    }

    dv = parse_dolby_vision_profile(track)
    is_hdr, hdr10plus, dv_profile = detect_hdr_from_mediainfo_track(track)

    assert dv["dolby_vision"] is True
    assert dv["dv_profile_major"] == 8
    assert dv["dv_profile"] == "8"
    assert dv["dv_codec_tag"] == "dvhe.08.06"
    assert dv["dv_level"] == "6"
    assert is_hdr is True
    assert hdr10plus is True
    assert dv_profile == "8"


def test_mediainfo_erkennt_auch_dvh1_dva1_und_dvav_codec_tags():
    for tag, profile in (("dvh1.08.06", 8), ("dva1.09.05", 9), ("dvav.09.05", 9)):
        dv = parse_dolby_vision_profile({"HDR_Format_Profile": tag})
        assert dv["dolby_vision"] is True
        assert dv["dv_profile_major"] == profile
        assert dv["dv_codec_tag"] == tag


def test_ffprobe_dovi_configuration_record_liefert_profil_und_level():
    stream = {
        "codec_name": "hevc",
        "codec_tag_string": "dvh1",
        "side_data_list": [
            {
                "side_data_type": "DOVI configuration record",
                "dv_version_major": 1,
                "dv_version_minor": 0,
                "dv_profile": 8,
                "dv_level": 6,
            }
        ],
    }

    dv = parse_dolby_vision_from_ffprobe_stream(stream)
    is_hdr, hdr10plus, profile = detect_hdr_from_ffprobe_stream(stream)

    assert dv["dolby_vision"] is True
    assert dv["dv_profile_major"] == 8
    assert dv["dv_profile"] == "8"
    assert dv["dv_level"] == "6"
    assert is_hdr is True
    assert hdr10plus is False
    assert profile == "8"


def test_dv_konflikt_wird_geloggt_und_strukturiertes_ffprobe_profil_gewinnt():
    warnings: list[str] = []
    mi = parse_dolby_vision_profile({"HDR_Format": "Dolby Vision, Profile 7, dvhe.07.06"})
    fp = parse_dolby_vision_from_ffprobe_stream(
        {"side_data_list": [{"side_data_type": "DOVI configuration record", "dv_profile": 8}]}
    )

    merged = merge_dolby_vision_info(mi, fp, warnings)

    assert merged["dv_profile_major"] == 8
    assert merged["dv_profile"] == "8"
    assert warnings
    assert "unterschiedliche Dolby-Vision-Profile" in warnings[0]


def test_8bit_avc_dolby_vision_wird_erkannt_aber_nicht_als_pipeline_support_erfunden():
    warnings: list[str] = []
    is_hdr, hdr10plus, dv_profile = validate_hdr_flags(
        codec="h264",
        bit_depth=8,
        pix_fmt="yuv420p",
        is_hdr=True,
        has_hdr10plus=False,
        dv_profile="9",
        warnings=warnings,
    )

    assert is_hdr is True
    assert hdr10plus is False
    assert dv_profile == "9"


def test_stream_builder_verliert_ffprobe_hdr10plus_nicht_wenn_mediainfo_track_existiert():
    warnings: list[str] = []
    mi = {
        "Format": "HEVC",
        "BitDepth": "10",
        "transfer_characteristics": "PQ",
        "colour_primaries": "BT.2020",
    }
    fp = {
        "codec_name": "hevc",
        "pix_fmt": "yuv420p10le",
        "color_transfer": "smpte2084",
        "color_primaries": "bt2020",
        "side_data_list": [
            {"side_data_type": "HDR Dynamic Metadata SMPTE2094-40 (HDR10+)"}
        ],
    }

    hdr_format, hdr10plus, dv = _hdr_state(
        mi,
        fp,
        codec="hevc",
        bit_depth=10,
        pix_fmt="yuv420p10le",
        analysis_warnings=warnings,
    )

    assert hdr_format == "hdr10plus"
    assert hdr10plus is True
    assert dv is False


def test_analyze_media_nutzt_kurzen_frame_fallback_fuer_hdr10plus(monkeypatch):
    import dragontools.core.media_analyzer as analyzer

    mi_json = {
        "media": {
            "track": [
                {"@type": "General", "Duration": "1000", "FileSize": "2048"},
                {
                    "@type": "Video",
                    "Format": "HEVC",
                    "Width": "1920",
                    "Height": "1080",
                    "BitDepth": "10",
                    "transfer_characteristics": "PQ",
                    "colour_primaries": "BT.2020",
                },
            ]
        }
    }
    fp_json = {
        "format": {"duration": "1.0", "size": "2048"},
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "hevc",
                "width": 1920,
                "height": 1080,
                "pix_fmt": "yuv420p10le",
                "color_transfer": "smpte2084",
                "color_primaries": "bt2020",
            }
        ],
    }
    monkeypatch.setattr(
        analyzer,
        "_analysis_payloads",
        lambda *_args, **_kwargs: (mi_json, fp_json, "MediaInfo.exe + ffprobe", []),
    )
    import dragontools.core.media_analyzer_dynamic_hdr as dynamic_hdr
    monkeypatch.setattr(
        dynamic_hdr,
        "_run_ffprobe_dynamic_hdr_frames",
        lambda *_args, **_kwargs: (
            {
                "frames": [
                    {
                        "side_data_list": [
                            {
                                "side_data_type": "HDR Dynamic Metadata SMPTE2094-40 (HDR10+)",
                                "application version": 1,
                            }
                        ]
                    }
                ]
            },
            [],
        ),
    )

    result = analyzer.analyze_media("Film_HDR10Plus.mkv", SimpleNamespace())

    assert result.has_hdr10plus is True
    assert result.primary_video is not None
    assert result.primary_video.hdr_format == "hdr10plus"
    assert "ffprobe-Frame-HDR" in result.analysis_source
    assert any("Frame-Fallback" in warning for warning in result.analysis_warnings)


def test_analyze_media_ffprobe_only_dv_profile_wird_in_media_info_uebernommen(monkeypatch):
    import dragontools.core.media_analyzer as analyzer

    fp_json = {
        "format": {"duration": "1.0", "size": "2048"},
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "hevc",
                "codec_tag_string": "dvh1",
                "width": 1920,
                "height": 1080,
                "pix_fmt": "yuv420p10le",
                "side_data_list": [
                    {
                        "side_data_type": "DOVI configuration record",
                        "dv_profile": 8,
                        "dv_level": 6,
                    }
                ],
            }
        ],
    }
    monkeypatch.setattr(
        analyzer,
        "_analysis_payloads",
        lambda *_args, **_kwargs: ({}, fp_json, "FFmpeg", []),
    )
    import dragontools.core.media_analyzer_dynamic_hdr as dynamic_hdr
    monkeypatch.setattr(
        dynamic_hdr,
        "_run_ffprobe_dynamic_hdr_frames",
        lambda *_args, **_kwargs: ({}, []),
    )

    result = analyzer.analyze_media("dv.mkv", SimpleNamespace())

    assert result.has_dv is True
    assert result.dv_profile == "8"
    assert result.dv_profile_major == 8
    assert result.dv_level == "6"
