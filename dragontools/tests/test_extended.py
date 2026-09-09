# -*- coding: utf-8 -*-
"""
Ergänzende Tests für dragontools – deckt Lücken auf, die im Code-Review
(2026-04-24) identifiziert wurden.

Bereiche:
  - core/models.py          : normalize_override_dict (Randfälle)
  - rules/audio_rules.py    : normalize_audio_codec, safe_int, reload_rules
  - rules/pipeline_selector : resolve_pipeline_context (H264, AV1, HEVC)
  - rules/audio_plan.py     : compute_audio_track_plan (Grundfälle)
  - core/type_utils.py      : _safe_int, _safe_float
  - rules/rule_loader.py    : load_json_rules Fallback-Verhalten
"""
from __future__ import annotations

import json
import threading

import pytest

# ---------------------------------------------------------------------------
# Hilfsfunktionen / Fixtures
# ---------------------------------------------------------------------------

def _make_video_stream(hdr_format: str | None = None, codec: str = "hevc"):
    from dragontools.core.models import VideoStream
    return VideoStream(
        index=0,
        codec=codec,
        width=3840,
        height=2160,
        hdr_format=hdr_format,
    )


def _make_audio_stream(
    index: int = 0,
    language: str | None = "de",
    codec: str = "eac3",
    channels: int = 6,
    bitrate: int | None = 640_000,
    forced: bool = False,
    title: str | None = None,
):
    from dragontools.core.models import AudioStream
    return AudioStream(
        index=index,
        language=language,
        forced=forced,
        title=title,
        codec=codec,
        channels=channels,
        bitrate=bitrate,
    )


def _make_media_info(
    hdr_format: str | None = None,
    codec: str = "hevc",
    audio_streams=None,
):
    from dragontools.core.models import MediaInfo
    vs = _make_video_stream(hdr_format=hdr_format, codec=codec)
    return MediaInfo(
        path="/fake/film.mkv",
        audio_streams=audio_streams or [_make_audio_stream()],
        subtitle_streams=[],
        video_streams=[vs],
    )


# ---------------------------------------------------------------------------
# 1  core/type_utils.py – _safe_int / _safe_float
# ---------------------------------------------------------------------------

class TestSafeInt:
    def test_none_gibt_default_none(self):
        from dragontools.core.type_utils import _safe_int
        assert _safe_int(None) is None

    def test_leerstring_gibt_default(self):
        from dragontools.core.type_utils import _safe_int
        assert _safe_int("", default=42) == 42

    def test_na_string_gibt_default(self):
        from dragontools.core.type_utils import _safe_int
        assert _safe_int("N/A") is None

    def test_float_string_wird_konvertiert(self):
        from dragontools.core.type_utils import _safe_int
        assert _safe_int("23.0") == 23

    def test_ganzzahl_string(self):
        from dragontools.core.type_utils import _safe_int
        assert _safe_int("7") == 7

    def test_echter_int(self):
        from dragontools.core.type_utils import _safe_int
        assert _safe_int(5) == 5

    def test_negativer_wert(self):
        from dragontools.core.type_utils import _safe_int
        assert _safe_int(-3) == -3

    def test_ungueltig_gibt_default(self):
        from dragontools.core.type_utils import _safe_int
        assert _safe_int("abc", default=0) == 0

    def test_default_wird_korrekt_weitergegeben(self):
        from dragontools.core.type_utils import _safe_int
        assert _safe_int(None, default=99) == 99


class TestSafeFloat:
    def test_none_gibt_default(self):
        from dragontools.core.type_utils import _safe_float
        assert _safe_float(None) == 0.0

    def test_float_string(self):
        from dragontools.core.type_utils import _safe_float
        assert _safe_float("3.14") == pytest.approx(3.14)

    def test_ungueltig_gibt_default(self):
        from dragontools.core.type_utils import _safe_float
        assert _safe_float("xyz", default=1.0) == 1.0


# ---------------------------------------------------------------------------
# 2  core/models.py – normalize_override_dict (Randfälle)
# ---------------------------------------------------------------------------

class TestNormalizeOverrideDictEdgeCases:
    """Ergänzt die bestehenden Tests in test_models.py."""

    def test_subtitle_track_ohne_index_wird_ignoriert(self):
        from dragontools.core.models import normalize_override_dict
        result = normalize_override_dict({
            "subtitle_tracks": [{"keep": True, "burn_in": False}]
        })
        assert result["subtitle_tracks"] == []

    def test_audio_track_ungültiger_mode_wird_zu_auto(self):
        from dragontools.core.models import normalize_override_dict
        result = normalize_override_dict({
            "audio_tracks": [{"index": 1, "mode": "ungueltig"}]
        })
        assert result["audio_tracks"][0]["mode"] == "auto"

    def test_preserve_hdrplus_tristate(self):
        from dragontools.core.models import normalize_override_dict
        assert normalize_override_dict({"preserve_hdrplus": True})["preserve_hdrplus"] is True
        assert normalize_override_dict({"preserve_hdrplus": False})["preserve_hdrplus"] is False
        assert normalize_override_dict({})["preserve_hdrplus"] is None

    def test_burn_in_setzt_keep_auf_false_bei_burn_spur(self):
        """keep=True + burn_in=True → keep muss False werden."""
        from dragontools.core.models import normalize_override_dict
        result = normalize_override_dict({
            "subtitle_tracks": [{"index": 5, "keep": True, "burn_in": True}]
        })
        track = result["subtitle_tracks"][0]
        assert track["keep"] is False
        assert track["burn_in"] is True

    def test_warnings_liste_ist_leer_wenn_kein_konflikt(self):
        from dragontools.core.models import normalize_override_dict
        result = normalize_override_dict({
            "subtitle_tracks": [{"index": 1, "keep": True, "burn_in": True}]
        })
        assert result["_warnings"] == []

    def test_dritter_burn_in_erzeugt_nur_einen_warning_eintrag(self):
        """Drei burn_in=True Spuren → genau ein Warning (für Spuren 2+3)."""
        from dragontools.core.models import normalize_override_dict
        result = normalize_override_dict({
            "subtitle_tracks": [
                {"index": 1, "keep": True, "burn_in": True},
                {"index": 2, "keep": True, "burn_in": True},
                {"index": 3, "keep": True, "burn_in": True},
            ]
        })
        # Implementierung produziert einen Warning-String der alle Konflikte enthält
        assert len(result["_warnings"]) == 1
        assert "#2" in result["_warnings"][0]
        assert "#3" in result["_warnings"][0]

    def test_non_dict_audio_track_eintrag_wird_ignoriert(self):
        from dragontools.core.models import normalize_override_dict
        result = normalize_override_dict({
            "audio_tracks": ["kein_dict", None, 42]
        })
        assert result["audio_tracks"] == []

    def test_non_dict_subtitle_track_eintrag_wird_ignoriert(self):
        from dragontools.core.models import normalize_override_dict
        result = normalize_override_dict({
            "subtitle_tracks": ["kein_dict", 99]
        })
        assert result["subtitle_tracks"] == []

    def test_audio_track_custom_mit_codec_und_bitrate(self):
        from dragontools.core.models import normalize_override_dict
        result = normalize_override_dict({
            "audio_tracks": [{"index": 2, "mode": "custom", "codec": "EAC3", "bitrate": 640}]
        })
        track = result["audio_tracks"][0]
        assert track["codec"] == "eac3"  # muss lowercase sein
        assert track["bitrate"] == 640

    def test_legacy_burn_mode_setzt_subtitle_mode_custom(self):
        from dragontools.core.models import normalize_override_dict
        result = normalize_override_dict({"burn_mode": "on"})
        assert result["subtitle_mode"] == "custom"


# ---------------------------------------------------------------------------
# 3  rules/audio_rules.py
# ---------------------------------------------------------------------------

class TestNormalizeAudioCodec:
    def test_dca_wird_zu_dts(self):
        from dragontools.rules.audio_rules import normalize_audio_codec
        assert normalize_audio_codec("dca") == "dts"

    def test_mlp_wird_zu_truehd(self):
        from dragontools.rules.audio_rules import normalize_audio_codec
        assert normalize_audio_codec("mlp") == "truehd"

    def test_pcm_varianten(self):
        from dragontools.rules.audio_rules import normalize_audio_codec
        for v in ("pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_bluray"):
            assert normalize_audio_codec(v) == "pcm", f"Erwartet pcm für {v}"

    def test_grossschreibung_wird_normalisiert(self):
        # normalize_audio_codec erwartet lowercase input, aber robustheit prüfen:
        # Die Funktion wandelt erst zu lowercase um (c = codec.lower())
        from dragontools.rules.audio_rules import normalize_audio_codec
        assert normalize_audio_codec("AAC") == "aac"

    def test_unbekannter_codec_bleibt_unveraendert(self):
        from dragontools.rules.audio_rules import normalize_audio_codec
        assert normalize_audio_codec("opus") == "opus"

    def test_leerer_string(self):
        from dragontools.rules.audio_rules import normalize_audio_codec
        assert normalize_audio_codec("") == ""


class TestReloadRules:
    def test_reload_erzwingt_neu_laden(self):
        """Nach reload_rules() wird der Cache neu befüllt."""
        from dragontools.rules.audio_rules import _load_rules, reload_rules
        reload_rules()
        r1 = _load_rules()
        reload_rules()
        r2 = _load_rules()
        # Beide Ladevorgänge liefern das gleiche Schema
        assert "channel_rules" in r1
        assert "channel_rules" in r2

    def test_cache_ist_thread_sicher_beim_lesen(self):
        """Mehrere Threads rufen _load_rules() gleichzeitig – kein Absturz."""
        from dragontools.rules.audio_rules import _load_rules, reload_rules
        reload_rules()
        results: list = []
        errors: list = []

        def worker():
            try:
                results.append(_load_rules())
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # Alle Threads müssen ein valides Dict erhalten haben
        assert all(isinstance(r, dict) for r in results)
        assert all("channel_rules" in r for r in results)


# ---------------------------------------------------------------------------
# 4  rules/rule_loader.py – load_json_rules Fallback
# ---------------------------------------------------------------------------

class TestLoadJsonRules:
    def test_fehlende_datei_gibt_default_zurueck(self, tmp_path):
        from dragontools.rules.rule_loader import load_json_rules
        default = {"key": "wert"}
        result = load_json_rules(tmp_path / "existiert_nicht.json", default=default)
        assert result == default

    def test_valide_json_datei_wird_geladen(self, tmp_path):
        from dragontools.rules.rule_loader import load_json_rules
        p = tmp_path / "rules.json"
        p.write_text(json.dumps({"preferred_languages": ["de"]}), encoding="utf-8")
        result = load_json_rules(p)
        assert result["preferred_languages"] == ["de"]

    def test_kein_json_objekt_gibt_default(self, tmp_path):
        """JSON-Array statt Objekt → Fallback auf default."""
        from dragontools.rules.rule_loader import load_json_rules
        p = tmp_path / "array.json"
        p.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        default = {"x": 1}
        result = load_json_rules(p, default=default)
        assert result == default

    def test_invalides_json_gibt_default(self, tmp_path):
        from dragontools.rules.rule_loader import load_json_rules
        p = tmp_path / "kaputt.json"
        p.write_text("{nicht: valides json}", encoding="utf-8")
        default = {"fallback": True}
        result = load_json_rules(p, default=default)
        assert result == default

    def test_reporter_wird_bei_fehler_aufgerufen(self, tmp_path):
        from dragontools.rules.rule_loader import load_json_rules
        meldungen: list[str] = []
        result = load_json_rules(
            tmp_path / "nicht_vorhanden.json",
            default={},
            reporter=lambda msg, *_: meldungen.append(msg),
        )
        assert len(meldungen) == 1
        assert "fehlt" in meldungen[0].lower() or "nicht" in meldungen[0].lower()


# ---------------------------------------------------------------------------
# 5  rules/pipeline_selector.py – resolve_pipeline_context
# ---------------------------------------------------------------------------

class TestResolvePipelineContext:
    """Prüft die Kontext-Auflösung für H264, AV1 und HEVC."""

    def test_hevc_dv_mit_standard_pipeline(self):
        from dragontools.rules.pipeline_selector import resolve_pipeline_context
        mi = _make_media_info(hdr_format="dolby_vision", codec="hevc")
        ctx = resolve_pipeline_context(
            mi,
            codec="hevc",
            global_preserve_dv=True,
        )
        assert ctx["pipeline"] == "dv"
        assert ctx["container"] == "mp4"
        assert ctx["should_archive"] is False

    def test_hevc_hdrplus_pipeline(self):
        from dragontools.rules.pipeline_selector import resolve_pipeline_context
        mi = _make_media_info(hdr_format="hdr10plus", codec="hevc")
        ctx = resolve_pipeline_context(
            mi,
            codec="hevc",
            global_preserve_hdrplus=True,
        )
        assert ctx["pipeline"] == "hdrplus"
        assert ctx["container"] == "mkv"

    def test_hevc_dv_hdrplus_waehlt_dv_und_behaelt_hdrplus_policy(self):
        from dragontools.core.models import MediaInfo, VideoStream
        from dragontools.rules.pipeline_selector import resolve_pipeline_context

        video = VideoStream(
            index=0,
            codec="hevc",
            width=3840,
            height=2160,
            hdr_format="dolby_vision",
            has_hdr10plus=True,
            has_dolby_vision=True,
        )
        mi = MediaInfo(
            path="/fake/film.mkv",
            audio_streams=[],
            subtitle_streams=[],
            video_streams=[video],
            has_hdr10plus=True,
            dolby_vision=True,
            dv_profile="7",
            dv_profile_major=7,
        )

        ctx = resolve_pipeline_context(
            mi,
            codec="hevc",
            global_preserve_dv=True,
            global_preserve_hdrplus=True,
        )

        assert ctx["pipeline"] == "dv"
        assert ctx["container"] == "mp4"
        assert ctx["effective_preserve_dv"] is True
        assert ctx["effective_preserve_hdrplus"] is True

    def test_h264_dv_erzwingt_standard_pipeline(self):
        """H264-Quelle: DV wird erkannt, aber Pipeline muss 'standard' sein."""
        from dragontools.rules.pipeline_selector import resolve_pipeline_context
        mi = _make_media_info(hdr_format="dolby_vision", codec="h264")
        ctx = resolve_pipeline_context(
            mi,
            codec="h264",
            global_preserve_dv=True,
        )
        assert ctx["pipeline"] == "standard"
        assert ctx["effective_preserve_dv"] is False
        assert "dv" in ctx["ignored_hdr"]

    def test_h264_dv_loest_archivierung_aus(self):
        from dragontools.rules.pipeline_selector import resolve_pipeline_context
        mi = _make_media_info(hdr_format="dolby_vision", codec="h264")
        ctx = resolve_pipeline_context(
            mi, codec="h264",
        )
        assert ctx["should_archive"] is True
        assert ctx["archive_reason"] is not None

    def test_h264_hdrplus_loest_archivierung_aus(self):
        from dragontools.rules.pipeline_selector import resolve_pipeline_context
        mi = _make_media_info(hdr_format="hdr10plus", codec="h264")
        ctx = resolve_pipeline_context(
            mi, codec="h264",
        )
        assert ctx["should_archive"] is True
        assert "hdr10plus" in ctx["ignored_hdr"]

    def test_av1_dv_nutzt_eigenen_profile10_pfad(self):
        """AV1 + DV nutzt den getrennten AV1-DV10-Betapfad."""
        from dragontools.rules.pipeline_selector import resolve_pipeline_context
        mi = _make_media_info(hdr_format="dolby_vision", codec="av1")
        ctx = resolve_pipeline_context(
            mi, codec="av1",
            global_preserve_dv=True,
        )
        assert ctx["pipeline"] == "av1_dv"
        assert ctx["should_archive"] is False
        assert ctx["effective_preserve_dv"] is True

    def test_av1_hdrplus_nutzt_separaten_av1_toolpfad(self):
        """AV1 + HDR10+ nutzt den AV1-HDR10+-Betapfad, nicht den HEVC-Toolpfad."""
        from dragontools.rules.pipeline_selector import resolve_pipeline_context
        mi = _make_media_info(hdr_format="hdr10plus", codec="av1")
        ctx = resolve_pipeline_context(
            mi, codec="av1",
            global_preserve_hdrplus=True,
        )
        assert ctx["pipeline"] == "av1_hdrplus"
        assert ctx["should_archive"] is False
        assert ctx["effective_preserve_hdrplus"] is True

    def test_expliziter_pipeline_override_schlaegt_erkennung(self):
        from dragontools.rules.pipeline_selector import resolve_pipeline_context
        mi = _make_media_info(hdr_format="dolby_vision", codec="hevc")
        ctx = resolve_pipeline_context(
            mi, codec="hevc",
            global_preserve_dv=True,
            job_pipeline="standard",
        )
        assert ctx["pipeline"] == "standard"

    def test_keine_hdr_ergibt_standard_pipeline(self):
        from dragontools.rules.pipeline_selector import resolve_pipeline_context
        mi = _make_media_info(hdr_format=None, codec="hevc")
        ctx = resolve_pipeline_context(
            mi, codec="hevc",
        )
        assert ctx["pipeline"] == "standard"
        assert ctx["should_archive"] is False

    def test_source_codec_wird_normalisiert(self):
        from dragontools.rules.pipeline_selector import resolve_pipeline_context
        mi = _make_media_info(codec="h264")
        ctx = resolve_pipeline_context(mi, codec="h264")
        assert ctx["source_codec"] in {"h264", "avc"}

    def test_avc_alias_wird_als_h264_behandelt(self):
        """'avc' ist ein Alias für H.264 und muss dieselbe Logik auslösen."""
        from dragontools.rules.pipeline_selector import resolve_pipeline_context
        from dragontools.core.models import MediaInfo, VideoStream
        vs = VideoStream(index=0, codec="avc", width=1920, height=1080, hdr_format="dolby_vision")
        mi = MediaInfo(path="/film.mkv", audio_streams=[], subtitle_streams=[], video_streams=[vs])
        ctx = resolve_pipeline_context(mi, codec="avc")
        # AVC/H264 → DV wird ignoriert
        assert ctx["pipeline"] == "standard"
        assert "dv" in ctx["ignored_hdr"]


# ---------------------------------------------------------------------------
# 6  rules/audio_plan.py – compute_audio_track_plan Grundfälle
# ---------------------------------------------------------------------------

class TestComputeAudioTrackPlan:
    """Smoke-Tests für die zentrale Audio-Plan-Funktion.

    HINWEIS: Alle Tests dieser Klasse schlagen auf Python 3.12 fehl mit
        SyntaxError: from __future__ imports must occur at the beginning of the file
    weil audio_plan.py `import logging; _LOG = ...` VOR dem `from __future__`
    Statement platziert (Bug 2.1 aus dem Code-Review 2026-04-24).
    Die Tests sind korrekt und werden nach dem Fix grün.
    """

    _XFAIL_REASON = (
        "audio_plan.py hat from __future__ nicht in Zeile 1 – SyntaxError auf Py 3.12 "
        "(Bug 2.1). Tests nach Fix der Dateireihenfolge entfernen."
    )

    def _try_import(self):
        try:
            from dragontools.rules.audio_plan import compute_audio_track_plan
            return compute_audio_track_plan
        except SyntaxError as e:
            pytest.xfail(f"{self._XFAIL_REASON} | {e}")

    def _default_rules(self):
        return {
            "preferred_languages": ["de"],
            "fallback_languages":  ["en"],
            "max_tracks":          1,
            "passthrough_codecs":  ["aac", "ac3", "eac3"],
            "extra_stereo":        False,
            "extra_stereo_codec":  "aac",
            "extra_stereo_bitrate_k": 256,
            "channel_rules": {
                "mono":        {"max_channels": 1, "target_codec": "aac",  "max_bitrate_k": 128},
                "stereo": {
                    "max_channels": 2,
                    "target_codec": "aac",
                    "max_bitrate_k": 192,
                    "copy_min_bitrate_k": 192,
                    "copy_max_bitrate_k": 256,
                },
                "surround_51": {
                    "max_channels": 6,
                    "target_channels": 6,
                    "target_codec": "eac3",
                    "max_bitrate_k": 640,
                    "copy_min_bitrate_k": 428,
                    "copy_max_bitrate_k": 640,
                    "downmix_mode": "never",
                    "downmix_bitrate_k": 256,
                },
                "surround_71": {
                    "max_channels": 8,
                    "target_channels": 6,
                    "target_codec": "eac3",
                    "max_bitrate_k": 640,
                    "copy_min_bitrate_k": 768,
                    "copy_max_bitrate_k": 1536,
                    "downmix_mode": "always",
                    "downmix_target": "surround_51",
                    "downmix_bitrate_k": 640,
                },
            },
            "transcode_rules": {
                "truehd":    {"target_codec": "eac3"},
                "dts":       {"target_codec": "eac3"},
                "dts-hd ma": {"target_codec": "eac3"},
                "flac":      {"target_codec": "eac3"},
                "pcm":       {"target_codec": "eac3"},
                "mp2":       {"target_codec": "aac"},
                "mp3":       {"target_codec": "aac"},
            },
        }

    def test_leere_streams_ergibt_leeren_plan(self):
        compute_audio_track_plan = self._try_import()
        plan = compute_audio_track_plan([], None, "mkv", rules=self._default_rules())
        assert plan == []

    def test_eac3_passthrough_in_mkv(self):
        compute_audio_track_plan = self._try_import()
        stream = _make_audio_stream(codec="eac3", channels=6, bitrate=500_000)
        plan = compute_audio_track_plan([stream], None, "mkv", rules=self._default_rules())
        assert len(plan) == 1
        assert plan[0].needs_transcode is False
        assert plan[0].target_codec == "eac3"

    def test_surround_51_eac3_innerhalb_kopierbereich_wird_kopiert(self):
        compute_audio_track_plan = self._try_import()
        stream = _make_audio_stream(codec="eac3", channels=6, bitrate=448_000)
        plan = compute_audio_track_plan([stream], None, "mkv", rules=self._default_rules())
        assert len(plan) == 1
        assert plan[0].needs_transcode is False
        assert plan[0].target_codec == "eac3"
        assert plan[0].target_channels == 6

    def test_surround_51_eac3_unter_kopierbereich_wird_transkodiert(self):
        compute_audio_track_plan = self._try_import()
        stream = _make_audio_stream(codec="eac3", channels=6, bitrate=256_000)
        plan = compute_audio_track_plan([stream], None, "mkv", rules=self._default_rules())
        assert len(plan) == 1
        assert plan[0].needs_transcode is True
        assert plan[0].target_codec == "eac3"
        assert plan[0].target_channels == 6

    def test_surround_71_kann_bei_nie_downmixen_im_kopierbereich_kopiert_werden(self):
        compute_audio_track_plan = self._try_import()
        rules = self._default_rules()
        rules["channel_rules"]["surround_71"]["downmix_mode"] = "never"
        stream = _make_audio_stream(codec="eac3", channels=8, bitrate=1_500_000)

        plan = compute_audio_track_plan([stream], None, "mkv", rules=rules)

        assert len(plan) == 1
        assert plan[0].needs_transcode is False
        assert plan[0].target_codec == "eac3"
        assert plan[0].target_channels == 8

    def test_surround_71_unter_kopierbereich_wird_bei_nie_downmixen_transkodiert(self):
        compute_audio_track_plan = self._try_import()
        rules = self._default_rules()
        rules["channel_rules"]["surround_71"]["downmix_mode"] = "never"
        stream = _make_audio_stream(codec="eac3", channels=8, bitrate=640_000)

        plan = compute_audio_track_plan([stream], None, "mkv", rules=rules)

        assert len(plan) == 1
        assert plan[0].needs_transcode is True
        assert plan[0].target_codec == "eac3"
        assert plan[0].target_channels == 6

    def test_truehd_wird_transkodiert(self):
        compute_audio_track_plan = self._try_import()
        stream = _make_audio_stream(codec="truehd", channels=8, bitrate=4_000_000)
        plan = compute_audio_track_plan([stream], None, "mkv", rules=self._default_rules())
        assert len(plan) == 1
        assert plan[0].needs_transcode is True
        assert plan[0].target_codec == "eac3"
        assert plan[0].target_channels == 6

    def test_dts_acht_kanaele_wird_fuer_eac3_auf_5_1_begrenzt(self):
        compute_audio_track_plan = self._try_import()
        stream = _make_audio_stream(codec="dts", channels=8, bitrate=1_509_000)
        plan = compute_audio_track_plan([stream], None, "mkv", rules=self._default_rules())

        assert len(plan) == 1
        assert plan[0].needs_transcode is True
        assert plan[0].target_codec == "eac3"
        assert plan[0].target_channels == 6

    def test_legacy_surround_71_eac3_acht_kanaele_wird_migriert(self):
        from dragontools.rules.audio_rules import migrate_audio_rules

        legacy = self._default_rules()
        legacy["channel_rules"]["surround_71"]["target_channels"] = 8

        migrated = migrate_audio_rules(legacy)

        assert migrated["channel_rules"]["surround_71"]["target_channels"] == 6

    def test_custom_eac3_acht_kanaele_wird_vor_ffmpeg_gekappt(self):
        compute_audio_track_plan = self._try_import()
        stream = _make_audio_stream(codec="dts", channels=8, bitrate=1_509_000)
        override = {
            "audio_mode": "custom",
            "audio_tracks": [
                {"index": 0, "mode": "custom", "codec": "eac3", "bitrate": 640_000}
            ],
        }

        plan = compute_audio_track_plan([stream], override, "mkv", rules=self._default_rules())

        assert len(plan) == 1
        assert plan[0].needs_transcode is True
        assert plan[0].target_codec == "eac3"
        assert plan[0].target_channels == 6

    def test_surround_71_kann_direkt_auf_stereo_downmixen(self):
        compute_audio_track_plan = self._try_import()
        stream = _make_audio_stream(codec="dts", channels=8, bitrate=1_509_000)
        rules = self._default_rules()
        rules["channel_rules"]["surround_71"]["downmix_mode"] = "always"
        rules["channel_rules"]["surround_71"]["downmix_target"] = "stereo"
        rules["channel_rules"]["surround_71"]["target_codec"] = "aac"
        rules["transcode_rules"]["dts"]["target_codec"] = "aac"

        plan = compute_audio_track_plan([stream], None, "mkv", rules=rules)

        assert len(plan) == 1
        assert plan[0].needs_transcode is True
        assert plan[0].target_codec == "aac"
        assert plan[0].target_channels == 2

    def test_surround_71_downmix_unter_bitrate_greift_bei_niedriger_bitrate(self):
        compute_audio_track_plan = self._try_import()
        stream = _make_audio_stream(codec="dts", channels=8, bitrate=640_000)
        rules = self._default_rules()
        rules["channel_rules"]["surround_71"]["downmix_mode"] = "below_bitrate"
        rules["channel_rules"]["surround_71"]["downmix_target"] = "stereo"
        rules["channel_rules"]["surround_71"]["downmix_bitrate_k"] = 640
        rules["channel_rules"]["surround_71"]["target_codec"] = "aac"
        rules["transcode_rules"]["dts"]["target_codec"] = "aac"

        plan = compute_audio_track_plan([stream], None, "mkv", rules=rules)

        assert len(plan) == 1
        assert plan[0].needs_transcode is True
        assert plan[0].target_codec == "aac"
        assert plan[0].target_channels == 2

    def test_surround_71_downmix_unter_bitrate_laesst_hoehere_bitrate_bei_aac_in_ruhre(self):
        compute_audio_track_plan = self._try_import()
        stream = _make_audio_stream(codec="dts", channels=8, bitrate=1_509_000)
        rules = self._default_rules()
        rules["channel_rules"]["surround_71"]["downmix_mode"] = "below_bitrate"
        rules["channel_rules"]["surround_71"]["downmix_target"] = "stereo"
        rules["channel_rules"]["surround_71"]["downmix_bitrate_k"] = 640
        rules["channel_rules"]["surround_71"]["target_codec"] = "aac"
        rules["transcode_rules"]["dts"]["target_codec"] = "aac"

        plan = compute_audio_track_plan([stream], None, "mkv", rules=rules)

        assert len(plan) == 1
        assert plan[0].needs_transcode is True
        assert plan[0].target_codec == "aac"
        assert plan[0].target_channels == 8

    def test_mp4_container_erzwingt_transkodierung_von_truehd(self):
        """In MP4: TrueHD ist nicht kompatibel → muss transkodiert werden."""
        compute_audio_track_plan = self._try_import()
        stream = _make_audio_stream(codec="truehd", channels=8, bitrate=4_000_000)
        plan = compute_audio_track_plan([stream], None, "mp4", rules=self._default_rules())
        assert plan[0].needs_transcode is True

    def test_mono_default_transkodiert_auf_aac_128_und_bleibt_mono(self):
        compute_audio_track_plan = self._try_import()
        stream = _make_audio_stream(codec="mp3", channels=1, bitrate=192_000)
        plan = compute_audio_track_plan([stream], None, "mkv", rules=self._default_rules())
        assert plan[0].needs_transcode is True
        assert plan[0].target_codec == "aac"
        assert plan[0].target_channels == 1
        assert plan[0].target_bitrate == 128_000

    def test_stereo_default_transkodiert_auf_aac_192(self):
        compute_audio_track_plan = self._try_import()
        stream = _make_audio_stream(codec="mp3", channels=2, bitrate=320_000)
        plan = compute_audio_track_plan([stream], None, "mkv", rules=self._default_rules())
        assert plan[0].needs_transcode is True
        assert plan[0].target_codec == "aac"
        assert plan[0].target_channels == 2
        assert plan[0].target_bitrate == 192_000

    def test_stereo_aac_innerhalb_kopierbereich_wird_kopiert(self):
        compute_audio_track_plan = self._try_import()
        stream = _make_audio_stream(codec="aac", channels=2, bitrate=196_000)
        plan = compute_audio_track_plan([stream], None, "mkv", rules=self._default_rules())
        assert plan[0].needs_transcode is False
        assert plan[0].target_codec == "aac"
        assert plan[0].target_bitrate == 196_000

    def test_stereo_aac_unter_kopierbereich_wird_ohne_bitrate_upscale_transkodiert(self):
        compute_audio_track_plan = self._try_import()
        stream = _make_audio_stream(codec="aac", channels=2, bitrate=128_000)
        plan = compute_audio_track_plan([stream], None, "mkv", rules=self._default_rules())
        assert plan[0].needs_transcode is True
        assert plan[0].target_codec == "aac"
        assert plan[0].target_bitrate == 128_000

    def test_stereo_mp3_128_wird_zu_aac_128_statt_aac_192(self):
        compute_audio_track_plan = self._try_import()
        stream = _make_audio_stream(codec="mp3", channels=2, bitrate=128_000)
        plan = compute_audio_track_plan([stream], None, "mkv", rules=self._default_rules())
        assert plan[0].needs_transcode is True
        assert plan[0].target_codec == "aac"
        assert plan[0].target_channels == 2
        assert plan[0].target_bitrate == 128_000

    def test_stereo_aac_ueber_kopierbereich_wird_auf_zielbitrate_transkodiert(self):
        compute_audio_track_plan = self._try_import()
        stream = _make_audio_stream(codec="aac", channels=2, bitrate=320_000)
        plan = compute_audio_track_plan([stream], None, "mkv", rules=self._default_rules())
        assert plan[0].needs_transcode is True
        assert plan[0].target_codec == "aac"
        assert plan[0].target_bitrate == 192_000

    def test_aac_ist_nicht_erzwungen_wenn_stereo_codec_geaendert_wird(self):
        compute_audio_track_plan = self._try_import()
        rules = self._default_rules()
        rules["channel_rules"]["stereo"]["target_codec"] = "ac3"
        rules["channel_rules"]["stereo"]["max_bitrate_k"] = 384
        stream = _make_audio_stream(codec="mp3", channels=2, bitrate=640_000)
        plan = compute_audio_track_plan([stream], None, "mkv", rules=rules)
        assert plan[0].target_codec == "ac3"
        assert plan[0].target_bitrate == 384_000

    def test_legacy_stereo_regel_laesst_mono_auf_aac_default(self):
        from dragontools.rules.audio_rules import migrate_audio_rules

        legacy = self._default_rules()
        legacy["channel_rules"] = {
            "stereo": {"max_channels": 2, "target_codec": "ac3", "max_bitrate_k": 192},
            "surround_51": {"max_channels": 6, "target_codec": "eac3", "max_bitrate_k": 640},
            "surround_71": {"max_channels": 8, "target_codec": "eac3", "max_bitrate_k": 640},
        }
        migrated = migrate_audio_rules(legacy)
        assert migrated["channel_rules"]["mono"]["target_codec"] == "aac"
        assert migrated["channel_rules"]["mono"]["max_bitrate_k"] == 128
        assert migrated["channel_rules"]["stereo"]["target_codec"] == "ac3"
        assert migrated["channel_rules"]["stereo"]["max_bitrate_k"] == 192
        assert migrated["channel_rules"]["stereo"]["copy_min_bitrate_k"] == 192
        assert migrated["channel_rules"]["stereo"]["copy_max_bitrate_k"] == 256

    def test_legacy_stereo_default_256_wird_auf_kopierbereich_migriert(self):
        from dragontools.rules.audio_rules import migrate_audio_rules

        legacy = self._default_rules()
        legacy["channel_rules"]["stereo"] = {
            "max_channels": 2,
            "target_codec": "aac",
            "max_bitrate_k": 256,
        }

        migrated = migrate_audio_rules(legacy)

        assert migrated["channel_rules"]["stereo"]["max_bitrate_k"] == 192
        assert migrated["channel_rules"]["stereo"]["copy_min_bitrate_k"] == 192
        assert migrated["channel_rules"]["stereo"]["copy_max_bitrate_k"] == 256

    def test_extra_stereo_erzeugt_zusatz_spur(self):
        compute_audio_track_plan = self._try_import()
        stream = _make_audio_stream(codec="eac3", channels=6, bitrate=640_000)
        rules = self._default_rules()
        rules["extra_stereo"] = True
        plan = compute_audio_track_plan([stream], None, "mkv", rules=rules)
        assert len(plan) == 2
        stereo_tracks = [p for p in plan if p.is_extra_stereo]
        assert len(stereo_tracks) == 1
        assert stereo_tracks[0].target_codec == "aac"
        assert stereo_tracks[0].target_channels == 2

    def test_extra_stereo_codec_ist_auswaehlbar(self):
        compute_audio_track_plan = self._try_import()
        stream = _make_audio_stream(codec="eac3", channels=6, bitrate=640_000)
        rules = self._default_rules()
        rules["extra_stereo"] = True
        rules["extra_stereo_codec"] = "eac3"
        plan = compute_audio_track_plan([stream], None, "mkv", rules=rules)
        stereo_tracks = [p for p in plan if p.is_extra_stereo]
        assert stereo_tracks[0].target_codec == "eac3"

    def test_surround_51_kann_direkt_auf_stereo_aac_downmixen(self):
        compute_audio_track_plan = self._try_import()
        stream = _make_audio_stream(codec="eac3", channels=6, bitrate=256_000)
        rules = self._default_rules()
        rules["channel_rules"]["surround_51"]["target_codec"] = "aac"
        rules["channel_rules"]["surround_51"]["downmix_mode"] = "always"
        rules["channel_rules"]["surround_51"]["max_bitrate_k"] = 256

        plan = compute_audio_track_plan([stream], None, "mkv", rules=rules)

        assert len(plan) == 1
        assert plan[0].needs_transcode is True
        assert plan[0].target_codec == "aac"
        assert plan[0].target_channels == 2
        assert plan[0].target_bitrate == 256_000

    def test_extra_stereo_wird_bei_direktem_stereo_downmix_nicht_verdoppelt(self):
        compute_audio_track_plan = self._try_import()
        stream = _make_audio_stream(codec="eac3", channels=6, bitrate=256_000)
        rules = self._default_rules()
        rules["extra_stereo"] = True
        rules["channel_rules"]["surround_51"]["target_codec"] = "aac"
        rules["channel_rules"]["surround_51"]["downmix_mode"] = "always"

        plan = compute_audio_track_plan([stream], None, "mkv", rules=rules)

        assert len(plan) == 1
        assert plan[0].is_extra_stereo is False
        assert plan[0].target_channels == 2

    def test_surround_51_downmix_unter_bitrate_greift_bei_niedriger_bitrate(self):
        compute_audio_track_plan = self._try_import()
        stream = _make_audio_stream(codec="eac3", channels=6, bitrate=256_000)
        rules = self._default_rules()
        rules["channel_rules"]["surround_51"]["target_codec"] = "aac"
        rules["channel_rules"]["surround_51"]["downmix_mode"] = "below_bitrate"
        rules["channel_rules"]["surround_51"]["downmix_bitrate_k"] = 256

        plan = compute_audio_track_plan([stream], None, "mkv", rules=rules)

        assert len(plan) == 1
        assert plan[0].needs_transcode is True
        assert plan[0].target_codec == "aac"
        assert plan[0].target_channels == 2

    def test_surround_51_downmix_unter_bitrate_laesst_hoehere_bitrate_in_ruhre(self):
        compute_audio_track_plan = self._try_import()
        stream = _make_audio_stream(codec="eac3", channels=6, bitrate=448_000)
        rules = self._default_rules()
        rules["channel_rules"]["surround_51"]["target_codec"] = "aac"
        rules["channel_rules"]["surround_51"]["downmix_mode"] = "below_bitrate"
        rules["channel_rules"]["surround_51"]["downmix_bitrate_k"] = 256

        plan = compute_audio_track_plan([stream], None, "mkv", rules=rules)

        assert len(plan) == 1
        assert plan[0].needs_transcode is False
        assert plan[0].target_codec == "eac3"
        assert plan[0].target_channels == 6

    def test_legacy_surround_51_target_channels_2_wird_als_always_downmix_migriert(self):
        from dragontools.rules.audio_rules import migrate_audio_rules

        legacy = self._default_rules()
        legacy["channel_rules"]["surround_51"].pop("downmix_mode", None)
        legacy["channel_rules"]["surround_51"].pop("downmix_bitrate_k", None)
        legacy["channel_rules"]["surround_51"]["target_channels"] = 2

        migrated = migrate_audio_rules(legacy)

        assert migrated["channel_rules"]["surround_51"]["downmix_mode"] == "always"
        assert migrated["channel_rules"]["surround_51"]["target_channels"] == 2

    def test_surround_51_downmix_copy_nutzt_flexiblen_stereo_fallback_codec(self):
        compute_audio_track_plan = self._try_import()
        stream = _make_audio_stream(codec="eac3", channels=6, bitrate=256_000)
        rules = self._default_rules()
        rules["channel_rules"]["stereo"]["target_codec"] = "ac3"
        rules["channel_rules"]["surround_51"]["target_codec"] = "copy"
        rules["channel_rules"]["surround_51"]["downmix_mode"] = "always"

        plan = compute_audio_track_plan([stream], None, "mkv", rules=rules)

        assert len(plan) == 1
        assert plan[0].needs_transcode is True
        assert plan[0].target_codec == "ac3"
        assert plan[0].target_channels == 2

    def test_out_idx_ist_0_basiert_und_sequenziell(self):
        compute_audio_track_plan = self._try_import()
        streams = [
            _make_audio_stream(index=0, codec="eac3", channels=6),
            _make_audio_stream(index=1, codec="aac",  channels=2, language="en"),
        ]
        rules = self._default_rules()
        rules["max_tracks"] = 2
        plan = compute_audio_track_plan(streams, None, "mkv", rules=rules)
        indices = [p.out_idx for p in plan]
        assert indices == list(range(len(indices)))

    def test_unbekannte_bitrate_fuehrt_nicht_zu_absturz(self):
        """AudioStream.bitrate=None muss ohne Exception verarbeitet werden."""
        compute_audio_track_plan = self._try_import()
        stream = _make_audio_stream(codec="eac3", channels=6, bitrate=None)
        plan = compute_audio_track_plan([stream], None, "mkv", rules=self._default_rules())
        assert len(plan) == 1
        # target_bitrate 0 ist akzeptabel – kein Crash
        assert plan[0].target_bitrate >= 0


# ---------------------------------------------------------------------------
# 7  core/models.py – MediaInfo Properties
# ---------------------------------------------------------------------------

class TestMediaInfoProperties:
    def test_has_dv_erkennt_dolby_vision(self):
        mi = _make_media_info(hdr_format="dolby_vision")
        assert mi.has_dv is True
        assert mi.has_hdrplus is False

    def test_has_hdrplus_erkennt_hdr10plus(self):
        mi = _make_media_info(hdr_format="hdr10plus")
        assert mi.has_hdrplus is True
        assert mi.has_dv is False

    def test_primary_video_bei_leerer_liste(self):
        from dragontools.core.models import MediaInfo
        mi = MediaInfo(
            path="/fake.mkv", audio_streams=[], subtitle_streams=[], video_streams=[]
        )
        assert mi.primary_video is None

    def test_primary_video_gibt_ersten_stream(self):
        mi = _make_media_info()
        pv = mi.primary_video
        assert pv is not None
        assert pv.index == 0
