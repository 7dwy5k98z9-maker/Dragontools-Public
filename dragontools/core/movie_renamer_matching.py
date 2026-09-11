# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from ..rules.renamer_rules import candidate_score_stages, manual_review_below, minimum_candidate_score

_AMBIGUOUS_LOW_STAGE_GAP = 0.08


def select_score_stage(
    candidates: list[Any],
    *,
    minimum_score_override: float | None = None,
    show_all_candidates: bool = False,
) -> tuple[list[Any], float]:
    """Return candidates from the first configured score stage that has hits."""
    if show_all_candidates:
        return list(candidates), 0.0
    if minimum_score_override is not None:
        threshold = max(0.0, min(1.0, float(minimum_score_override)))
        return _at_least(candidates, threshold), threshold
    stages = candidate_score_stages()
    for threshold in stages:
        matches = _at_least(candidates, threshold)
        if matches:
            return matches, threshold
    return [], (stages[-1] if stages else minimum_candidate_score())


def stage_warning(threshold: float) -> str | None:
    primary = minimum_candidate_score()
    if threshold <= 0.0:
        return "Manuelle Suche: alle Provider-Treffer werden angezeigt."
    if threshold + 1e-9 < primary:
        return (
            "Erweiterte Fuzzy-Suche verwendet: Mindestübereinstimmung "
            f"{int(round(threshold * 100))} %."
        )
    return None


def candidate_status(
    candidates: list[Any],
    *,
    threshold: float,
    target_exists: bool,
) -> tuple[str, str | None]:
    """Classify an already selected candidate without ever auto-accepting fallbacks."""
    if target_exists:
        return "conflict", "Zieldatei existiert bereits."
    if threshold <= 0.0:
        return "manual_review", "Manuelle Trefferliste: Auswahl bitte prüfen."
    if threshold + 1e-9 < minimum_candidate_score():
        if _ambiguous_lowest_stage(candidates, threshold):
            return (
                "fallback_ambiguous",
                "Letzte Fuzzy-Stufe liefert mehrere ähnlich schwache Treffer; bitte Kandidat manuell prüfen.",
            )
        return (
            "fallback_review",
            "Treffer stammt aus einer reduzierten Fuzzy-Stufe und sollte manuell geprüft werden.",
        )
    selected = candidates[0] if candidates else None
    if selected is not None and float(getattr(selected, "score", 0.0) or 0.0) < manual_review_below():
        return "manual_review", "Treffer ist unsicher und sollte manuell geprüft werden."
    return "ok", None


def _ambiguous_lowest_stage(candidates: list[Any], threshold: float) -> bool:
    stages = candidate_score_stages()
    if not stages or threshold > min(stages) + 1e-9 or len(candidates) < 2:
        return False
    scores = sorted(
        (float(getattr(item, "score", 0.0) or 0.0) for item in candidates),
        reverse=True,
    )
    return (scores[0] - scores[1]) < _AMBIGUOUS_LOW_STAGE_GAP


def _at_least(candidates: list[Any], threshold: float) -> list[Any]:
    return [
        item for item in candidates
        if float(getattr(item, "score", 0.0) or 0.0) >= threshold
    ]
