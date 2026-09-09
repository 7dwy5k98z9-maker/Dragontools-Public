# -*- coding: utf-8 -*-
from __future__ import annotations

from dragontools.core.models import AudioStream, SubtitleStream


def _audio(index: int, language: str, *, title: str = "", codec: str = "eac3", channels: int = 6):
    return AudioStream(
        index=index,
        language=language,
        forced=False,
        title=title,
        codec=codec,
        channels=channels,
        bitrate=640_000,
    )


def _sub(
    index: int,
    language: str,
    *,
    forced: bool = False,
    codec: str = "subrip",
    event_count: int | None = None,
):
    return SubtitleStream(
        index=index,
        language=language,
        forced=forced,
        title="",
        codec=codec,
        event_count=event_count,
    )


def test_audio_prioritaet_nimmt_naechste_vorhandene_sprache():
    from dragontools.rules.audio_rules import choose_audio_streams

    streams = [_audio(1, "eng"), _audio(2, "jpn")]
    rules = {
        "language_priority": ["de", "en", "ja"],
        "max_languages": 1,
        "tracks_per_language": 1,
    }

    chosen = choose_audio_streams(streams, rules)

    assert [stream.index for stream in chosen] == [1]


def test_audio_fallback_uebernimmt_alle_wenn_keine_prioritaet_passt():
    from dragontools.rules.audio_rules import choose_audio_streams

    streams = [_audio(1, "eng"), _audio(2, "jpn")]
    rules = {
        "language_priority": ["fr"],
        "max_languages": 1,
        "tracks_per_language": 1,
        "fallback_if_no_priority_match": "keep_all",
    }

    chosen = choose_audio_streams(streams, rules)

    assert [stream.index for stream in chosen] == [1, 2]


def test_audio_kommentarspur_wird_uebersprungen():
    from dragontools.rules.audio_rules import choose_audio_streams

    streams = [
        _audio(1, "deu", title="Regie Kommentar", channels=8),
        _audio(2, "deu", title="Hauptton", channels=6),
    ]
    rules = {
        "language_priority": ["de"],
        "max_languages": 1,
        "tracks_per_language": 1,
        "ignore_commentary_tracks": True,
    }

    chosen = choose_audio_streams(streams, rules)

    assert [stream.index for stream in chosen] == [2]


def test_audio_max_sprachen_begrenzt_sprachgruppen():
    from dragontools.rules.audio_rules import choose_audio_streams

    streams = [_audio(1, "eng"), _audio(2, "jpn"), _audio(3, "fra")]
    rules = {
        "language_priority": ["de", "en", "ja", "fr"],
        "max_languages": 2,
        "tracks_per_language": 1,
    }

    chosen = choose_audio_streams(streams, rules)

    assert [stream.index for stream in chosen] == [1, 2]


def test_untertitel_burn_nutzt_feste_burn_sprache():
    from dragontools.rules.subtitle_rules import compute_subtitle_plan

    streams = [
        _sub(3, "deu", forced=True),
        _sub(4, "jpn", forced=True),
    ]
    rules = {
        "language_priority": ["de", "en"],
        "max_languages": 1,
        "tracks_per_language": 1,
        "burn_in_rules": {
            "auto_burn_forced": True,
            "burn_language": "ja",
            "burn_fallback": "none",
            "ask_if_ambiguous": False,
        },
        "keep_rules": {
            "keep_forced": False,
            "keep_selected_languages": False,
        },
    }

    plan = compute_subtitle_plan(streams, subtitle_rules=rules)

    assert plan.burn_sub is not None
    assert plan.burn_sub.index == 4


def test_forced_burn_waehlt_bestes_format_trotz_mehrerer_kandidaten():
    from dragontools.rules.subtitle_rules import compute_subtitle_plan

    streams = [
        _sub(3, "deu", forced=True, codec="hdmv_pgs_subtitle"),
        _sub(4, "deu", forced=True, codec="ass"),
        _sub(5, "deu", forced=True, codec="subrip"),
    ]
    rules = {
        "language_priority": ["de"],
        "max_languages": 1,
        "tracks_per_language": 1,
        "preferred_formats": ["subrip", "srt", "ass", "ssa", "hdmv_pgs_subtitle"],
        "burn_in_rules": {
            "auto_burn_forced": True,
            "burn_language": "de",
            "ask_if_ambiguous": True,
        },
        "keep_rules": {
            "keep_forced": False,
            "keep_selected_languages": False,
        },
    }

    plan = compute_subtitle_plan(streams, subtitle_rules=rules)

    assert plan.burn_sub is not None
    assert plan.burn_sub.index == 5
    assert plan.burn_blocked_reason is None


def test_forced_burn_bleibt_mehrdeutig_bei_gleichem_bestformat():
    from dragontools.rules.subtitle_rules import compute_subtitle_plan

    streams = [
        _sub(3, "deu", forced=True, codec="subrip"),
        _sub(4, "deu", forced=True, codec="subrip"),
        _sub(5, "deu", forced=True, codec="ass"),
    ]
    rules = {
        "language_priority": ["de"],
        "max_languages": 1,
        "tracks_per_language": 1,
        "preferred_formats": ["subrip", "srt", "ass", "ssa", "hdmv_pgs_subtitle"],
        "burn_in_rules": {
            "auto_burn_forced": True,
            "burn_language": "de",
            "ask_if_ambiguous": True,
        },
        "keep_rules": {
            "keep_forced": False,
            "keep_selected_languages": False,
        },
    }

    plan = compute_subtitle_plan(streams, subtitle_rules=rules)

    assert plan.burn_sub is None
    assert plan.burn_blocked_reason == "ambiguous"
    assert [stream.index for stream in plan.burn_candidates] == [3, 4]


def test_forced_burn_plausibilitaet_unter_grenze_brennt_normal():
    from dragontools.rules.subtitle_rules import compute_subtitle_plan

    streams = [_sub(3, "deu", forced=True, codec="subrip", event_count=60)]
    rules = {
        "language_priority": ["de"],
        "max_languages": 1,
        "tracks_per_language": 1,
        "burn_in_rules": {
            "auto_burn_forced": True,
            "burn_language": "de",
            "ask_if_ambiguous": False,
        },
        "keep_rules": {
            "keep_forced": False,
            "keep_selected_languages": False,
        },
    }

    plan = compute_subtitle_plan(streams, subtitle_rules=rules, media_duration_s=1800.0)

    assert plan.burn_sub is not None
    assert plan.burn_sub.index == 3
    assert plan.burn_blocked_reason is None
    assert plan.burn_warnings == ()


def test_forced_burn_plausibilitaet_warnt_bei_mittlerer_dichte():
    from dragontools.rules.subtitle_rules import compute_subtitle_plan

    streams = [_sub(3, "deu", forced=True, codec="subrip", event_count=100)]
    rules = {
        "language_priority": ["de"],
        "max_languages": 1,
        "tracks_per_language": 1,
        "burn_in_rules": {
            "auto_burn_forced": True,
            "burn_language": "de",
            "ask_if_ambiguous": False,
        },
        "keep_rules": {
            "keep_forced": False,
            "keep_selected_languages": False,
        },
    }

    plan = compute_subtitle_plan(streams, subtitle_rules=rules, media_duration_s=1800.0)

    assert plan.burn_sub is not None
    assert plan.burn_blocked_reason is None
    assert plan.burn_warnings
    assert 3.0 < (plan.burn_event_rate or 0.0) <= 5.0


def test_forced_burn_plausibilitaet_blockiert_full_sub_und_rettet_spur():
    from dragontools.rules.subtitle_rules import compute_subtitle_plan

    streams = [
        _sub(3, "deu", forced=True, codec="subrip", event_count=220),
        _sub(4, "deu", forced=False, codec="subrip", event_count=400),
    ]
    rules = {
        "language_priority": ["de"],
        "max_languages": 1,
        "tracks_per_language": 1,
        "burn_in_rules": {
            "auto_burn_forced": True,
            "burn_language": "de",
            "ask_if_ambiguous": False,
        },
        "keep_rules": {
            "keep_forced": False,
            "keep_selected_languages": True,
            "keep_regular": True,
        },
    }

    plan = compute_subtitle_plan(streams, subtitle_rules=rules, media_duration_s=1800.0)

    assert plan.burn_sub is None
    assert plan.burn_blocked_reason == "forced_full_sub_suspected"
    assert [stream.index for stream in plan.keep_streams] == [3, 4]
    assert plan.burn_warnings


def test_forced_burn_plausibilitaet_rettet_sidecar_zusaetzlich_trotz_limit():
    from dragontools.rules.subtitle_rules import compute_subtitle_plan

    streams = [
        _sub(3, "deu", forced=True, codec="subrip", event_count=220),
        _sub(4, "deu", forced=False, codec="subrip", event_count=400),
    ]
    rules = {
        "language_priority": ["de"],
        "max_languages": 1,
        "tracks_per_language": 1,
        "burn_in_rules": {
            "auto_burn_forced": True,
            "burn_language": "de",
            "ask_if_ambiguous": False,
        },
        "keep_rules": {
            "keep_forced": False,
            "keep_selected_languages": True,
            "keep_regular": True,
        },
    }

    plan = compute_subtitle_plan(
        streams,
        subtitle_rules=rules,
        container_copy_supported=False,
        media_duration_s=1800.0,
    )

    assert list(plan.keep_streams) == []
    assert [stream.index for stream in plan.external_streams] == [4, 3]


def test_untertitel_keep_nimmt_nur_erste_vorhandene_prioritaetssprache():
    from dragontools.rules.subtitle_rules import compute_subtitle_plan

    streams = [_sub(3, "eng"), _sub(4, "jpn")]
    rules = {
        "language_priority": ["de", "en", "ja"],
        "max_languages": 1,
        "tracks_per_language": 1,
        "fallback_if_no_priority_match": "keep_none",
        "burn_in_rules": {"auto_burn_forced": False},
        "keep_rules": {
            "keep_forced": False,
            "keep_selected_languages": True,
            "keep_regular": True,
        },
    }

    plan = compute_subtitle_plan(streams, subtitle_rules=rules)

    assert [stream.index for stream in plan.keep_streams] == [3]


def test_alte_untertitelregel_behaelt_weiterhin_deutsch():
    from dragontools.rules.subtitle_rules import compute_subtitle_plan

    streams = [_sub(3, "deu"), _sub(4, "eng")]
    legacy_rules = {
        "keep_rules": {
            "keep_forced": True,
            "keep_all_german": True,
            "keep_german_if_no_burn": False,
            "keep_english_fallback": False,
        },
    }

    plan = compute_subtitle_plan(streams, subtitle_rules=legacy_rules)

    assert [stream.index for stream in plan.keep_streams] == [3]


def test_alte_untertitelregel_respektiert_max_ein_sub_je_sprache():
    from dragontools.rules.subtitle_rules import compute_subtitle_plan

    streams = [
        _sub(12, "deu", forced=False, codec="subrip"),
        _sub(13, "deu", forced=False, codec="ass"),
        _sub(14, "eng", forced=False, codec="subrip"),
    ]
    legacy_rules = {
        "preferred_languages": ["de", "deu", "ger"],
        "fallback_languages": ["en", "eng"],
        "preferred_formats": ["subrip", "ass"],
        "keep_rules": {
            "keep_forced": False,
            "keep_all_german": True,
            "keep_german_if_no_burn": False,
            "keep_english_fallback": False,
        },
    }

    plan = compute_subtitle_plan(streams, subtitle_rules=legacy_rules)

    assert [stream.index for stream in plan.keep_streams] == [12]


def test_dv_sidecar_begrenzt_untertitel_und_bevorzugt_srt():
    from dragontools.rules.subtitle_rules import compute_subtitle_plan

    streams = [
        _sub(3, "deu", forced=True, codec="hdmv_pgs_subtitle"),
        _sub(4, "deu", forced=True, codec="ass"),
        _sub(5, "deu", forced=False, codec="subrip"),
        _sub(6, "deu", forced=False, codec="hdmv_pgs_subtitle"),
        _sub(7, "eng", forced=False, codec="subrip"),
    ]
    rules = {
        "language_priority": ["de", "en"],
        "max_languages": 1,
        "tracks_per_language": 1,
        "fallback_if_no_priority_match": "keep_none",
        "preferred_formats": ["subrip", "srt", "ass", "ssa", "hdmv_pgs_subtitle", "dvd_subtitle"],
        "burn_in_rules": {"auto_burn_forced": False},
        "keep_rules": {
            "keep_forced": True,
            "keep_selected_languages": True,
            "keep_regular": True,
        },
    }

    plan = compute_subtitle_plan(
        streams,
        subtitle_rules=rules,
        container_copy_supported=False,
    )

    assert list(plan.keep_streams) == []
    assert [stream.index for stream in plan.external_streams] == [5]


def test_dv_sidecar_alte_formatliste_erkennt_srt_alias():
    from dragontools.rules.subtitle_rules import compute_subtitle_plan

    streams = [
        _sub(3, "deu", forced=False, codec="ass"),
        _sub(4, "deu", forced=False, codec="srt"),
    ]
    rules = {
        "language_priority": ["de"],
        "max_languages": 1,
        "tracks_per_language": 1,
        "preferred_formats": ["subrip", "ass", "hdmv_pgs_subtitle", "dvd_subtitle"],
        "burn_in_rules": {"auto_burn_forced": False},
        "keep_rules": {
            "keep_forced": True,
            "keep_selected_languages": True,
            "keep_regular": True,
        },
    }

    plan = compute_subtitle_plan(
        streams,
        subtitle_rules=rules,
        container_copy_supported=False,
    )

    assert [stream.index for stream in plan.external_streams] == [4]


def test_dv_sidecar_exportiert_keine_forced_subs_nach_forced_burn():
    from dragontools.rules.subtitle_rules import compute_subtitle_plan

    streams = [
        _sub(3, "deu", forced=True, codec="ass"),
        _sub(4, "deu", forced=True, codec="hdmv_pgs_subtitle"),
    ]
    rules = {
        "language_priority": ["de"],
        "max_languages": 1,
        "tracks_per_language": 1,
        "preferred_formats": ["subrip", "srt", "ass", "ssa", "hdmv_pgs_subtitle"],
        "burn_in_rules": {
            "auto_burn_forced": True,
            "burn_language": "de",
            "burn_fallback": "none",
            "ask_if_ambiguous": False,
        },
        "keep_rules": {
            "keep_forced": True,
            "keep_selected_languages": False,
            "keep_regular": False,
        },
    }

    plan = compute_subtitle_plan(
        streams,
        subtitle_rules=rules,
        container_copy_supported=False,
    )

    assert plan.burn_sub is not None
    assert plan.burn_sub.index == 3
    assert list(plan.external_streams) == []


def test_dv_sidecar_custom_override_darf_mehrere_subs_exportieren():
    from dragontools.rules.subtitle_rules import compute_subtitle_plan

    streams = [
        _sub(3, "deu", forced=False, codec="subrip"),
        _sub(4, "deu", forced=False, codec="ass"),
        _sub(5, "eng", forced=False, codec="subrip"),
    ]
    rules = {
        "language_priority": ["de"],
        "max_languages": 1,
        "tracks_per_language": 1,
        "burn_in_rules": {"auto_burn_forced": False},
        "keep_rules": {
            "keep_forced": True,
            "keep_selected_languages": True,
            "keep_regular": True,
        },
    }
    override = {
        "subtitle_mode": "custom",
        "subtitle_tracks": [
            {"index": 3, "keep": True},
            {"index": 4, "keep": True},
            {"index": 5, "keep": True},
        ],
    }

    plan = compute_subtitle_plan(
        streams,
        subtitle_rules=rules,
        file_override=override,
        container_copy_supported=False,
    )

    assert list(plan.keep_streams) == []
    assert [stream.index for stream in plan.external_streams] == [3, 4, 5]
