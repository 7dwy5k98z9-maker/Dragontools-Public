# -*- coding: utf-8 -*-
"""Pure decision logic for applying a renamer metadata candidate."""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from .movie_renamer import RenameProposal, SeriesRenameProposal, build_series_target_filename, build_target_filename
from .path_syntax import path_compare_key
from ..rules.renamer_rules import manual_review_below, minimum_candidate_score

_GENERATED_WARNINGS = {
    "Zieldatei existiert bereits.",
    "Treffer ist unsicher und sollte manuell geprüft werden.",
    "Treffer stammt aus einer reduzierten Fuzzy-Stufe und sollte manuell geprüft werden.",
    "Letzte Fuzzy-Stufe liefert mehrere ähnlich schwache Treffer; bitte Kandidat manuell prüfen.",
    "Manuelle Trefferliste: Auswahl bitte prüfen.",
}


@dataclass(frozen=True, slots=True)
class CandidateDecision:
    proposal: RenameProposal
    index: int
    year: int | None
    provider_label: str
    score_text: str


def base_candidate_warnings(warnings: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(item for item in warnings if item not in _GENERATED_WARNINGS)


def apply_candidate_decision(proposal: RenameProposal, candidate_index: int, source_path: Path) -> CandidateDecision:
    if not proposal.candidates:
        raise ValueError("Proposal enthält keine Kandidaten.")
    index = max(0, min(int(candidate_index), len(proposal.candidates) - 1))
    selected = proposal.candidates[index]
    warnings = list(base_candidate_warnings(proposal.warnings))
    target_name, year = _target_name_and_year(proposal, selected)
    target_path = source_path.with_name(target_name)
    target_exists = target_path.exists() and path_compare_key(target_path) != path_compare_key(source_path)
    status = _status_for(proposal, selected.score, target_exists, warnings)
    updated = replace(
        proposal,
        selected=selected,
        target_name=target_name,
        target_path=target_path,
        status=status,
        confidence=selected.score,
        warnings=tuple(warnings),
        target_exists=target_exists,
    )
    provider = str(getattr(selected, "provider", "") or "").strip().lower()
    provider_label = {"thetvdb": "TheTVDB", "tmdb": "TMDB"}.get(provider, provider or "Metadaten")
    return CandidateDecision(
        proposal=updated,
        index=index,
        year=year,
        provider_label=provider_label,
        score_text=_score_text(proposal, selected),
    )


def _target_name_and_year(proposal, selected):
    if isinstance(proposal, SeriesRenameProposal):
        target_name = build_series_target_filename(
            selected.series, selected.season, selected.episode, selected.episode_title, proposal.parsed.suffix,
        )
        return target_name, selected.year or proposal.parsed.year
    return build_target_filename(selected.title, selected.year or proposal.parsed.year, proposal.parsed.suffix), selected.year or proposal.parsed.year


def _status_for(proposal, score: float, target_exists: bool, warnings: list[str]) -> str:
    if target_exists:
        warnings.append("Zieldatei existiert bereits.")
        return "conflict"
    threshold = float(getattr(proposal, "minimum_score_used", 0.0) or 0.0)
    search_mode = getattr(proposal, "search_mode", "auto")
    if proposal.status == "fallback_ambiguous":
        warnings.append("Letzte Fuzzy-Stufe liefert mehrere ähnlich schwache Treffer; bitte Kandidat manuell prüfen.")
        return "fallback_ambiguous"
    if threshold <= 0.0 and search_mode != "auto":
        warnings.append("Manuelle Trefferliste: Auswahl bitte prüfen.")
        return "manual_review"
    if threshold < minimum_candidate_score():
        warnings.append("Treffer stammt aus einer reduzierten Fuzzy-Stufe und sollte manuell geprüft werden.")
        return "fallback_review"
    if score < manual_review_below():
        warnings.append("Treffer ist unsicher und sollte manuell geprüft werden.")
        return "manual_review"
    return "ok"


def _score_text(proposal, selected) -> str:
    text = f"{int(round(selected.score * 100))} %"
    threshold = float(getattr(proposal, "minimum_score_used", 0.0) or 0.0)
    if 0.0 < threshold < minimum_candidate_score():
        text += f" · Fallback {int(round(threshold * 100))} %"
    elif threshold <= 0.0 and getattr(proposal, "search_mode", "auto") != "auto":
        text += " · alle Treffer"
    reason = str(getattr(selected, "match_reason", "") or "").strip()
    if reason:
        text += f" · {reason}"
    return text
