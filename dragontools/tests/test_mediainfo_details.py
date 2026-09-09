# -*- coding: utf-8 -*-
from __future__ import annotations

from dragontools.core.mediainfo_details import build_mediainfo_display_details


def test_mediainfo_details_zeigt_bitraten_und_spuren():
    payload = {
        "media": {
            "track": [
                {
                    "@type": "General",
                    "Format": "Matroska",
                    "FileSize": "1450000000",
                    "Duration": "1430100.000000",
                    "OverallBitRate": "8110000",
                },
                {
                    "@type": "Video",
                    "StreamOrder": "0",
                    "Format": "HEVC",
                    "Format_Profile": "Main 10",
                    "Width": "1920",
                    "Height": "1080",
                    "FrameRate": "23.976",
                    "FrameRate_Mode": "CFR",
                    "FrameCount": "34286",
                    "BitRate": "7600000",
                    "BitDepth": "10",
                    "ChromaSubsampling": "4:2:0",
                    "colour_primaries": "BT.709",
                    "transfer_characteristics": "BT.709",
                    "matrix_coefficients": "BT.709",
                    "Encoded_Library": "x265",
                },
                {
                    "@type": "Audio",
                    "StreamOrder": "1",
                    "Format": "AAC",
                    "Channels": "2",
                    "BitRate": "256000",
                    "SamplingRate": "48000",
                    "Language_String": "Deutsch",
                    "Title": "German",
                    "Default": "Yes",
                },
                {
                    "@type": "Text",
                    "StreamOrder": "2",
                    "Format": "UTF-8",
                    "CodecID": "S_TEXT/UTF8",
                    "Language_String": "Deutsch",
                    "Forced": "Yes",
                },
            ]
        }
    }

    details = build_mediainfo_display_details(
        "C:/Videos/Film.mkv",
        payload=payload,
    )

    overview = dict(details.overview_rows)
    video = dict(details.video_rows)

    assert overview["Gesamtbitrate"] == "8.11 Mb/s"
    assert overview["Videobitrate"] == "7.60 Mb/s"
    assert overview["Dauer"] == "23:50.1 (1430.1s)"
    assert video["Auflösung"] == "1.920×1.080"
    assert video["Bit-Tiefe"] == "10 Bit"
    assert details.audio_rows[0]["Bitrate"] == "256 kb/s"
    assert details.audio_rows[0]["Kanäle"] == "Stereo"
    assert details.audio_rows[0]["Flags"] == "Default"
    assert details.subtitle_rows[0]["Flags"] == "Forced"


def test_mediainfo_details_schaetzt_videobitrate_wenn_video_bitrate_fehlt():
    payload = {
        "media": {
            "track": [
                {"@type": "General", "Format": "Matroska", "OverallBitRate": "900000"},
                {"@type": "Video", "Format": "AVC", "Width": "1280", "Height": "720"},
                {"@type": "Audio", "Format": "AAC", "Channels": "2", "BitRate": "128000"},
            ]
        }
    }

    details = build_mediainfo_display_details("C:/Videos/Folge.mkv", payload=payload)

    assert dict(details.overview_rows)["Videobitrate"] == "772 kb/s (geschätzt)"
