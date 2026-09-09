# -*- coding: utf-8 -*-
from __future__ import annotations


def _stream(codec: str = "eac3", channels: int = 2, bitrate: int = 224_000):
    from dragontools.core.models import AudioStream

    return AudioStream(
        index=0,
        language="de",
        forced=False,
        title=None,
        codec=codec,
        channels=channels,
        bitrate=bitrate,
    )


def _rules(**audio_processing):
    from dragontools.rules.audio_rules import migrate_audio_rules

    rules = migrate_audio_rules({})
    rules["language_priority"] = ["de"]
    rules["max_languages"] = 1
    rules["tracks_per_language"] = 1
    rules["audio_processing"].update(audio_processing)
    return rules


def test_drc_for_ac3_source_forces_transcode_and_input_arg():
    from dragontools.rules.audio_plan import audio_input_args_for_plan, compute_audio_track_plan

    plan = compute_audio_track_plan(
        [_stream(codec="ac3", channels=2, bitrate=224_000)],
        None,
        "mkv",
        rules=_rules(drc_enabled=True, drc_scale=1.5),
        apply_language_rules=False,
    )

    assert len(plan) == 1
    assert plan[0].needs_transcode is True
    assert plan[0].drc_scale == 1.5
    assert audio_input_args_for_plan(plan) == ["-drc_scale", "1.5"]


def test_drc_for_aac_source_is_documented_but_does_not_force_transcode():
    from dragontools.rules.audio_plan import audio_input_args_for_plan, compute_audio_track_plan

    plan = compute_audio_track_plan(
        [_stream(codec="aac", channels=2, bitrate=224_000)],
        None,
        "mkv",
        rules=_rules(drc_enabled=True, drc_scale=2.0),
        apply_language_rules=False,
    )

    assert len(plan) == 1
    assert plan[0].needs_transcode is False
    assert plan[0].drc_scale is None
    assert any("DRC übersprungen" in note for note in plan[0].processing_notes)
    assert audio_input_args_for_plan(plan) == []


def test_loudnorm_forces_transcode_and_adds_filter():
    from dragontools.rules.audio_plan import audio_filter_chain, compute_audio_track_plan

    plan = compute_audio_track_plan(
        [_stream(codec="aac", channels=2, bitrate=224_000)],
        None,
        "mkv",
        rules=_rules(loudnorm_enabled=True, loudnorm_i=-18.0),
        apply_language_rules=False,
    )

    assert len(plan) == 1
    assert plan[0].needs_transcode is True
    assert "loudnorm=I=-18" in audio_filter_chain(plan[0])


def test_file_override_can_disable_global_audio_processing():
    from dragontools.rules.audio_plan import audio_filter_chain, audio_input_args_for_plan, compute_audio_track_plan

    rules = _rules(drc_enabled=True, drc_scale=2.0, loudnorm_enabled=True, loudnorm_i=-17.0)
    override = {
        "audio_drc": {"mode": "off", "scale": 2.0},
        "audio_loudnorm": {"mode": "off", "i": -17.0},
    }

    plan = compute_audio_track_plan(
        [_stream(codec="eac3", channels=2, bitrate=224_000)],
        override,
        "mkv",
        rules=rules,
        apply_language_rules=False,
    )

    assert len(plan) == 1
    assert plan[0].needs_transcode is False
    assert audio_filter_chain(plan[0]) == ""
    assert audio_input_args_for_plan(plan) == []
