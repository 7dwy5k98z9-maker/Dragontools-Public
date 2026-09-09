# -*- coding: utf-8 -*-
from __future__ import annotations

from dragontools.core.media_analyzer import (
    _build_audio_streams,
    _build_video_streams,
    build_pix_fmt_from_mediainfo,
)


def _track(color_space="YUV", chroma="4:2:0", bit_depth="10"):
    return {
        "@type": "Video",
        "Format": "HEVC",
        "Width": "3840",
        "Height": "2160",
        "ColorSpace": color_space,
        "ChromaSubsampling": chroma,
        "BitDepth": bit_depth,
    }


class TestBuildPixFmtFromMediaInfo:
    def test_yuv_420_10_wird_yuv420p10le(self):
        assert build_pix_fmt_from_mediainfo(_track("YUV", "4:2:0", "10")) == "yuv420p10le"

    def test_yuv_420_8_wird_yuv420p(self):
        assert build_pix_fmt_from_mediainfo(_track("YUV", "4:2:0", "8")) == "yuv420p"

    def test_yuv_422_10_wird_yuv422p10le(self):
        assert build_pix_fmt_from_mediainfo(_track("YUV", "4:2:2", "10")) == "yuv422p10le"

    def test_yuv_444_10_wird_yuv444p10le(self):
        assert build_pix_fmt_from_mediainfo(_track("YUV", "4:4:4", "10")) == "yuv444p10le"

    def test_yuv_420_12_wird_yuv420p12le(self):
        assert build_pix_fmt_from_mediainfo(_track("YUV", "4:2:0", "12")) == "yuv420p12le"

    def test_fehlende_werte_ergeben_none(self):
        assert build_pix_fmt_from_mediainfo({}) is None

    def test_ungueltige_bitdepth_ergibt_none(self):
        assert build_pix_fmt_from_mediainfo(_track("YUV", "4:2:0", "abc")) is None

    def test_unbekannter_colorspace_ergibt_none(self):
        assert build_pix_fmt_from_mediainfo(_track("RGB", "4:2:0", "10")) is None

    def test_unbekanntes_chroma_ergibt_none(self):
        assert build_pix_fmt_from_mediainfo(_track("YUV", "4:1:1", "10")) is None


def test_build_video_streams_speichert_mediainfo_pix_fmt_im_model():
    streams = _build_video_streams([_track("YUV", "4:2:0", "10")], [], {}, [])

    assert len(streams) == 1
    assert streams[0].pix_fmt == "yuv420p10le"
    assert streams[0].bit_depth == 10



def test_build_video_streams_speichert_frame_infos_im_model():
    track = _track("YUV", "4:2:0", "8")
    track.update(
        {
            "Duration": "1441565",
            "FrameCount": "34563",
            "FrameRate": "23.976",
            "FrameRate_Mode": "Constant",
        }
    )

    streams = _build_video_streams([track], [], {}, [])

    assert streams[0].duration_s == 1441.565
    assert streams[0].frame_count == 34563
    assert streams[0].frame_rate == "24000/1001"
    assert streams[0].frame_rate_mode == "CFR"


def test_audio_streams_nutzen_ffprobe_globalindex_bei_bluray_reihenfolge():
    mi_audios = [
        {"@type": "Audio", "Format": "DTS", "Language": "Japanese", "StreamOrder": "0"},
        {"@type": "Audio", "Format": "AC-3", "Language": "German", "StreamOrder": "1"},
    ]
    fp_audios = [
        {"index": 2, "codec_type": "audio", "codec_name": "dts", "tags": {"language": "jpn"}},
        {"index": 3, "codec_type": "audio", "codec_name": "ac3", "tags": {"language": "deu"}},
    ]

    streams = _build_audio_streams(mi_audios, fp_audios)

    assert [stream.index for stream in streams] == [2, 3]
    assert streams[0].language == "jpn"
    assert streams[1].language == "de"
