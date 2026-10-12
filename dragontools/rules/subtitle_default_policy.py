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
    """Adjust output copies only; source flags and forced flags stay intact.

    If both language priorities agree and playback audio uses another known
    language, prefer a complete subtitle in that preferred language. One
    selected subtitle becomes default, including its sidecar representation.
    """
    selected = list(plan.keep_streams) + list(plan.external_streams)
    if plan.burn_sub is not None:
        selected.append(plan.burn_sub)
    if not selected or not audio_streams:
        return plan
    sub_priority = normalize_language_priority(migrate_subtitle_rules(subtitle_rules).get('language_priority'))
    rules = migrate_audio_rules(audio_rules if audio_rules is not None else audio_plan.load_audio_rules())
    audio_priority = normalize_language_priority(rules.get('language_priority'))
    if not sub_priority or not audio_priority or sub_priority[0] != audio_priority[0]:
        return plan
    preferred = sub_priority[0]
    candidates = [s for s in selected if canonical_lang(s.language) == preferred]
    if not candidates:
        return plan
    decisions = audio_plan.compute_audio_track_plan(
        list(audio_streams), file_override, 'mkv', rules=rules,
        apply_language_rules=apply_audio_language_rules,
    )
    playback = [d for d in decisions if not d.is_extra_stereo]
    if not playback:
        return plan
    primary = next((d for d in playback if audio_plan.output_default_for_decision(d)), playback[0])
    language = canonical_lang(primary.stream.language)
    if language in {'', 'und', 'mul', 'zxx', preferred}:
        return plan
    # Preserve the planned language/format order within full and forced tracks.
    target = min(candidates, key=lambda s: bool(s.forced))
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
