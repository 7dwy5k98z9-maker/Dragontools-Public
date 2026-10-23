"""Default subtitles for playback in the preferred language."""
from __future__ import annotations

from copy import copy
from dataclasses import replace

from ..core.lang_codes import canonical_lang, normalize_language_priority
from . import audio_plan
from .audio_rules import migrate_audio_rules
from .subtitle_rule_config import migrate_subtitle_rules


def apply_subtitle_default_policy(
    plan, *, audio_streams, file_override, subtitle_rules,
    audio_rules=None, apply_audio_language_rules=True,
):
    """Set one selected output default without changing source/forced flags."""
    selected = list(plan.keep_streams) + list(plan.external_streams)
    if plan.burn_sub is not None:
        selected.append(plan.burn_sub)
    if not selected:
        return plan
    subtitle_settings = migrate_subtitle_rules(subtitle_rules)
    default = subtitle_settings['default_subtitle']
    mode = default['mode']
    if mode == 'preserve':
        return plan
    priority = default['language_priority']
    if mode != 'always':
        if not audio_streams:
            return plan
        rules = migrate_audio_rules(audio_rules if audio_rules is not None else audio_plan.load_audio_rules())
        audio_priority = normalize_language_priority(rules.get('language_priority'))
        reference = default['audio_language']
        if reference == 'audio_priority':
            reference = audio_priority[0] if audio_priority else ''
        if mode == 'legacy':
            priority = subtitle_settings['language_priority'][:1]
            if not priority or not audio_priority or priority[0] != audio_priority[0]:
                return plan
            reference = priority[0]
        language = _playback_language(audio_streams, file_override, rules, apply_audio_language_rules)
        if language is None or not reference or language == reference:
            return plan
        if mode == 'legacy' and language in {'', 'und', 'mul', 'zxx'}:
            return plan
        # An unknown tag cannot confirm matching audio. In the explicit
        # conditional mode it therefore receives subtitles as well.
    candidates = [s for s in selected if canonical_lang(s.language) in priority]
    if not candidates:
        return plan
    # Language rank precedes full/forced preference; format order is stable.
    target = min(candidates, key=lambda s: (priority.index(canonical_lang(s.language)), bool(s.forced)))
    target_index = int(target.index)

    def output_stream(stream):
        if stream is None:
            return None
        result = copy(stream)
        result.default = int(stream.index) == target_index
        return result

    return replace(
        plan,
        burn_sub=output_stream(plan.burn_sub),
        keep_streams=tuple(output_stream(s) for s in plan.keep_streams),
        external_streams=tuple(output_stream(s) for s in plan.external_streams),
    )


def _playback_language(audio_streams, file_override, rules, apply_language_rules):
    decisions = audio_plan.compute_audio_track_plan(
        list(audio_streams), file_override, 'mkv', rules=rules,
        apply_language_rules=apply_language_rules,
    )
    playback = [d for d in decisions if not d.is_extra_stereo]
    if not playback:
        return None
    primary = next((d for d in playback if audio_plan.output_default_for_decision(d)), playback[0])
    return canonical_lang(primary.stream.language)
