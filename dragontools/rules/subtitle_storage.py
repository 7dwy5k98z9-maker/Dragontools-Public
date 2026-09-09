# -*- coding: utf-8 -*-
from __future__ import annotations

from ..core.models import SubtitleStream
from ..core.type_utils import _safe_bool
from .subtitle_plan_models import MP4SubtitleStoragePlan, SubtitlePlan
from .subtitle_rule_config import IMAGE_SUBTITLE_CODECS, TEXT_SUBTITLE_CODECS
from .subtitle_selection import _dedupe_streams

def mp4_sidecars_enabled(subtitle_rules: dict | None) -> bool:
    """Liefert die globale MP4-Sidecar-Einstellung mit Legacy-Fallback.

    ``dv_extract_external_subs`` war bis Schema v3 ausschließlich für DV-MP4
    zuständig. Beim Upgrade wird dessen Wert bewusst übernommen, damit sich das
    Verhalten bestehender Installationen nicht still ändert.
    """
    rules = subtitle_rules or {}
    if "mp4_sidecars_enabled" in rules:
        return _safe_bool(rules.get("mp4_sidecars_enabled"), True)
    if "dv_extract_external_subs" in rules:
        return _safe_bool(rules.get("dv_extract_external_subs"), True)
    return True


def build_mp4_subtitle_storage_plan(
    plan: SubtitlePlan,
    *,
    subtitle_rules: dict | None,
    preserve_burn_candidate: bool = False,
) -> MP4SubtitleStoragePlan:
    """Teilt ausgewählte MP4-Untertitel in intern/extern auf.

    ``preserve_burn_candidate`` ist für Copy-/Remux-Pfade gedacht. Dort kann
    ein vom Regelwerk zum Burn-In bestimmter Track nicht eingebrannt werden und
    muss deshalb wie ein Keep-Track erhalten bleiben.
    """
    selected = list(plan.keep_streams)
    burn_sub = plan.burn_sub
    if (
        preserve_burn_candidate
        and burn_sub is not None
        and all(int(s.index) != int(burn_sub.index) for s in selected)
    ):
        selected.insert(0, burn_sub)
    selected = _dedupe_streams(selected)

    if mp4_sidecars_enabled(subtitle_rules):
        return MP4SubtitleStoragePlan((), tuple(selected))

    internal: list[SubtitleStream] = []
    external: list[SubtitleStream] = []
    for stream in selected:
        codec = str(getattr(stream, "codec", "") or "").strip().lower()
        if codec in IMAGE_SUBTITLE_CODECS:
            external.append(stream)
        elif codec in TEXT_SUBTITLE_CODECS:
            internal.append(stream)
        else:
            # Unbekannte Formate niemals blind in MP4 muxen. Der normale
            # Planner filtert sie bereits aus; diese Absicherung hält den
            # Containerpfad fail-safe.
            external.append(stream)

    return MP4SubtitleStoragePlan(tuple(internal), tuple(external))
