# -*- coding: utf-8 -*-
"""Suche und Auflösung bestehender Serien-/Specials-Ordner."""
from __future__ import annotations

from pathlib import Path
from ..core.path_syntax import join_user_path
from .move_path_helpers import (
    sanitize_win_segment, _dir_year_suffix, _normalize_for_dir_match,
    _series_dir_fuzzy_match, _strip_dir_year_suffix,
)

def find_series_dir_candidates(base: str | None, series_name: str, year: int | None = None) -> list[str]:
    """Liefert bestehende Serienordner-Kandidaten unterhalb des Basisordners.

    Matching-Logik:
      Exakte normalisierte Treffer zuerst, danach kontrollierte Schreibvarianten
      (Project/Projekt, ein fehlendes fuehrendes Wort bei langen Titeln).
      Ein Substring-Match ("mao" in "xxxxxxxdungen mao") wird NICHT akzeptiert.

    Tolerierte Unterschiede:
      - Verschiedene Apostrophe (MAO's vs MAO´s)
      - Bindestrich optional bzw. typografisch verschieden (Special Ops Lioness vs Special Ops - Lioness)
      - Leerzeichen zwischen Wörtern (werden zum Vergleich entfernt)
      - Das Jahr bleibt Editionsmerkmal: Ein bekanntes Jahr filtert auf diese
        Edition. Ohne Jahr bleiben alle passenden Ordner fuer die Auswahl.
    """
    if not base:
        return []
    bp = Path(base)
    if not bp.exists():
        return []

    safe_series = sanitize_win_segment(series_name, fallback="Unbekannt")
    # Für den Vergleich den Roh-Namen normalisieren. sanitize_win_segment()
    # bleibt ausschließlich für einen tatsächlich erzeugbaren Windows-Pfad.
    wanted_year = (int(year) if year else None) or _dir_year_suffix(str(series_name or ""))
    needle = _normalize_for_dir_match(_strip_dir_year_suffix(str(series_name or "")))
    exact_dir = bp / safe_series
    exact_candidates: list[Path] = []
    fuzzy_candidates: list[Path] = []

    for d in bp.iterdir():
        # Bekannte Editionen vor jedem Dateisystemzugriff filtern.
        if wanted_year and _dir_year_suffix(d.name) != wanted_year:
            continue
        # Jahres-Suffix entfernen, dann normalisieren
        dir_name_without_year = _strip_dir_year_suffix(d.name)
        dn = _normalize_for_dir_match(dir_name_without_year)
        # Erst den Namen vergleichen: is_dir() kann auf Netzlaufwerken einen
        # eigenen Zugriff auslösen und ist für fremde Serien unnötig.
        if dn == needle:
            if d.is_dir():
                exact_candidates.append(d)
        elif _series_dir_fuzzy_match(dir_name_without_year, series_name) and d.is_dir():
            fuzzy_candidates.append(d)

    exact_candidates.sort(key=lambda p: p.name.lower())
    fuzzy_candidates.sort(key=lambda p: p.name.lower())
    # Ein exakter Schreibtreffer darf alternative passende Ordner nicht
    # verstecken. Mehrere Kandidaten werden durch das bestehende UI aufgeloest.
    candidates = exact_candidates + fuzzy_candidates
    if exact_dir in candidates:
        # Unter Windows ist Path-Gleichheit unabhaengig von der Schreibweise.
        # Trotzdem den tatsaechlich gelesenen Ordnernamen zurueckgeben.
        exact_candidate = candidates.pop(candidates.index(exact_dir))
        candidates.insert(0, exact_candidate)

    return [str(p) for p in candidates]


def find_existing_series_dir(base: str | None, series_name: str, year: int | None = None) -> str | None:
    """Sucht einen bestehenden Serienordner unterhalb des Basisordners."""
    candidates = find_series_dir_candidates(base, series_name, year=year)
    return candidates[0] if candidates else None


def resolve_series_root_dir(base: str | None, series_name: str) -> str | None:
    """Zentrale Serienwurzel-Entscheidung für Preflight und Runtime."""
    if not base:
        return None

    safe_series = sanitize_win_segment(series_name, fallback="Unbekannt")
    candidates = find_series_dir_candidates(base, safe_series)
    if candidates:
        return candidates[0]
    return join_user_path(base, safe_series)


# Bekannte Ordnernamen für Staffel 0 / Specials (Groß-/Kleinschreibung egal)
_SPECIALS_FOLDER_NAMES: tuple[str, ...] = (
    "specials", "special",
    "staffel 00", "staffel 0", "staffel00", "staffel0",
    "sonderfolgen", "sonderfolge",
    "extras", "extra",
    "ova", "ovas",
    "filme", "film",
    "movie", "movies",
    "specials & movies", "specials and movies",
)


def find_specials_subfolder(series_root: str | Path) -> str | None:
    """Sucht in einem Serienordner nach einem existierenden Specials/S00-Unterordner.

    Gibt den Pfad des ersten gefundenen Ordners zurück, dessen Name (klein)
    zu einem der bekannten Specials-Namen passt.  None wenn keiner existiert.
    """
    root = Path(series_root)
    if not root.is_dir():
        return None
    for d in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not d.is_dir():
            continue
        if d.name.lower() in _SPECIALS_FOLDER_NAMES:
            return str(d)
    return None
