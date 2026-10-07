"""Shared identity review after automatic or manually selected candidates."""
from .german_title_variants import fold_german_umlauts
from .renamer_year_safety import apply_year_review


def apply_rename_identity_review(status, warnings, parsed, selected, candidates, *, explicit=False):
    status = apply_year_review(status, warnings, parsed.year, selected.year)
    reason = None
    if not explicit and hasattr(parsed, 'episode_numbers'):
        if (selected.season, selected.episode) != (parsed.season, parsed.episode):
            reason = 'Episodenidentität weicht vom Dateinamen ab; Auswahl manuell prüfen.'
        elif len(parsed.episode_numbers) > 1:
            reason = ('Mehrfachfolge: automatische Metadatensuche bestätigt nur die Start-Episode; '
                'Episodencode vollständig erhalten und manuelle Prüfung erforderlich.')
    if not explicit and parsed.year is None and _same_title_remakes(selected, candidates):
        reason = 'Gleichnamige Metadaten mit unterschiedlichen Jahren; Jahr oder Zuordnung manuell bestätigen.'
    if reason:
        if reason not in warnings:
            warnings.append(reason)
        if status == 'ok':
            status = 'manual_review'
    return status


def _same_title_remakes(selected, candidates):
    title = fold_german_umlauts(getattr(selected, 'series', getattr(selected, 'title', ''))).strip()
    years = {candidate.year for candidate in candidates if candidate.year is not None
        and fold_german_umlauts(getattr(candidate, 'series', getattr(candidate, 'title', ''))).strip() == title
        and candidate.score >= selected.score - 0.08}
    return len(years) > 1
