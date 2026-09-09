# -*- coding: utf-8 -*-
"""Tests für core/models.py – normalize_override_dict"""
from dragontools.core.models import MediaInfo, VideoStream, normalize_override_dict


class TestNormalizeOverrideDict:
    def test_none_ergibt_sichere_defaults(self):
        result = normalize_override_dict(None)
        assert result["audio_mode"] == "auto"
        assert result["subtitle_mode"] == "auto"
        assert result["audio_tracks"] == []
        assert result["subtitle_tracks"] == []
        assert result["imax"] is False
        assert result["preserve_dv"] is None
        assert result["preserve_hdrplus"] is None
        assert result["_warnings"] == []

    def test_leeres_dict_entspricht_none(self):
        assert normalize_override_dict({}) == normalize_override_dict(None)

    def test_audio_mode_auto_bleibt_auto(self):
        result = normalize_override_dict({"audio_mode": "auto"})
        assert result["audio_mode"] == "auto"

    def test_audio_mode_custom_bleibt_custom(self):
        result = normalize_override_dict({"audio_mode": "custom"})
        assert result["audio_mode"] == "custom"

    def test_ungültiger_audio_mode_wird_zu_auto(self):
        result = normalize_override_dict({"audio_mode": "ungültig"})
        assert result["audio_mode"] == "auto"

    def test_audio_track_ohne_index_wird_ignoriert(self):
        result = normalize_override_dict({"audio_tracks": [{"mode": "custom"}]})
        assert result["audio_tracks"] == []

    def test_audio_track_mit_gültigem_index(self):
        result = normalize_override_dict({
            "audio_tracks": [{"index": 1, "mode": "auto"}]
        })
        assert len(result["audio_tracks"]) == 1
        assert result["audio_tracks"][0]["index"] == 1
        assert result["audio_tracks"][0]["mode"] == "auto"

    def test_doppelter_burn_in_erzeugt_warning(self):
        result = normalize_override_dict({
            "subtitle_tracks": [
                {"index": 1, "keep": True, "burn_in": True},
                {"index": 2, "keep": True, "burn_in": True},
            ]
        })
        assert len(result["_warnings"]) == 1
        # Nur Spur 1 wird eingebrannt
        track2 = next(t for t in result["subtitle_tracks"] if t["index"] == 2)
        assert track2["burn_in"] is False

    def test_burn_in_deaktiviert_keep_auf_der_burn_spur(self):
        result = normalize_override_dict({
            "subtitle_tracks": [
                {"index": 3, "keep": True, "burn_in": True},
            ]
        })
        track = result["subtitle_tracks"][0]
        assert track["burn_in"] is True
        assert track["keep"] is False  # burn_in schließt keep aus

    def test_preserve_dv_tristate(self):
        assert normalize_override_dict({"preserve_dv": True})["preserve_dv"] is True
        assert normalize_override_dict({"preserve_dv": False})["preserve_dv"] is False
        assert normalize_override_dict({})["preserve_dv"] is None

    def test_imax_flag(self):
        assert normalize_override_dict({"imax": True})["imax"] is True
        assert normalize_override_dict({"imax": False})["imax"] is False
        assert normalize_override_dict({})["imax"] is False

    def test_processing_mode_strip_only(self):
        assert normalize_override_dict({"processing_mode": "strip_only"})["processing_mode"] == "strip_only"
        assert normalize_override_dict({"processing_mode": "kaputt"})["processing_mode"] == "auto"
        assert normalize_override_dict({"strip_only": True})["processing_mode"] == "strip_only"

    def test_legacy_audio_action_wird_erkannt(self):
        # Wenn audio_action != "auto" → audio_mode sollte "custom" werden
        result = normalize_override_dict({"audio_action": "copy"})
        assert result["audio_mode"] == "custom"
        assert result["_legacy"]["audio_action"] == "copy"


class TestMediaInfoHdrFlags:
    def test_dv_und_hdr10plus_koennen_gleichzeitig_erkannt_werden(self):
        video = VideoStream(
            index=0,
            codec="hevc",
            width=3840,
            height=2160,
            hdr_format="dolby_vision",
            has_hdr10plus=True,
            has_dolby_vision=True,
        )
        media = MediaInfo(
            path="/fake/film.mkv",
            audio_streams=[],
            subtitle_streams=[],
            video_streams=[video],
            has_hdr10plus=True,
            dolby_vision=True,
        )

        assert media.has_dv is True
        assert media.has_hdrplus is True


def test_override_string_booleans_are_normalized_without_python_bool_trap():
    result = normalize_override_dict({
        "strip_only": "false",
        "imax": "false",
        "preserve_dv": "false",
        "preserve_hdrplus": "0",
        "subtitle_tracks": [
            {"index": "1.0", "keep": "true", "burn_in": "false"},
        ],
    })

    assert result["processing_mode"] == "auto"
    assert result["imax"] is False
    assert result["preserve_dv"] is False
    assert result["preserve_hdrplus"] is False
    assert result["subtitle_tracks"] == [{"index": 1, "keep": True, "burn_in": False}]
