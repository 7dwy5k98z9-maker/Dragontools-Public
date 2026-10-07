# -*- coding: utf-8 -*-
"""Dateiname→Metadaten-Suchanfrage und textuelle Normalisierung."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path

from .online_metadata_types import (
    MovieMetadataSuggestion, ParsedMovieQuery, ParsedSeriesQuery, SeriesMetadataSuggestion,
)
from ..rules.renamer_rules import strip_configured_release_groups
from .german_title_variants import fold_german_umlauts

_VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".m4v", ".mov", ".ts", ".m2ts", ".wmv"}


def _metadata_input_stem(value: str | Path) -> tuple[str, str]:
    """Return (raw, stem/text) independent of the host OS path syntax."""
    raw = str(value)
    leaf = raw.replace("\\", "/").rsplit("/", 1)[-1]
    leaf_path = Path(leaf)
    text = leaf_path.stem if leaf_path.suffix.lower() in _VIDEO_EXTENSIONS else raw
    return raw, text

def _extract_metadata_year(text: str) -> tuple[int | None, re.Match[str] | None]:
    """Return a defensible release-year token without eating numeric titles.

    Parenthesized years are explicit metadata. Bare four-digit numbers are
    ambiguous (``1917``, ``1899``, ``Blade Runner 2049``), so only accept a
    plausible release year when meaningful title text already precedes it.
    The last plausible token wins, allowing e.g. ``2001 A Space Odyssey 1968``.
    """
    explicit = re.search(r"\((19\d{2}|20\d{2})\)", text)
    if explicit:
        return int(explicit.group(1)), explicit

    max_release_year = datetime.now().year + 1
    candidates: list[re.Match[str]] = []
    for match in re.finditer(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)", text):
        value = int(match.group(1))
        prefix = text[: match.start()].strip(" -._")
        if value > max_release_year or not re.search(r"\w", prefix, flags=re.UNICODE):
            continue
        candidates.append(match)
    if not candidates:
        return None, None
    chosen = candidates[-1]
    return int(chosen.group(1)), chosen


def parse_movie_query(value: str | Path) -> ParsedMovieQuery:
    raw, text = _metadata_input_stem(value)
    text, _configured_groups = strip_configured_release_groups(text)
    text = re.sub(r"[_\s]?(H264|H265|AV1|HEVC|x265|x264)$", "", text, flags=re.I).strip()
    text = text.replace("_", " ").replace(".", " ")
    text = re.sub(r"\s+", " ", text).strip()

    year, m = _extract_metadata_year(text)
    if m is not None:
        text = text[: m.start()].strip(" -._")

    cleanup_patterns = (
        r"\b(German|Deutsch|Ger|Eng|DL|Subbed|Sub|Dubbed|WEB|WEBRip|BluRay|BDRip|"
        r"UHD|2160p|1080p|720p|HDR|DV|DoVi|HDR10|HDR10Plus|AAC|EAC3|DTS|"
        r"H264|H265|HEVC|AVC|AV1|x264|x265)\b.*$"
    )
    text = re.sub(cleanup_patterns, "", text, flags=re.I).strip(" -._")
    text = re.sub(r"\s+", " ", text).strip()
    return ParsedMovieQuery(title=text or _metadata_input_stem(value)[1], year=year)


def parse_series_query(value: str | Path) -> ParsedSeriesQuery:
    # DragonTools patch: series release normalization v2
    raw, text = _metadata_input_stem(value)
    text, _configured_groups = strip_configured_release_groups(text)

    # Normale Trenner vereinheitlichen. Bindestriche bleiben zunaechst erhalten,
    # damit Scene-/Release-Schemata wie "tvs-watson-eac3-..." erkennbar bleiben.
    text = text.replace("_", " ").replace(".", " ")

    # Episodenmarker und alles dahinter fuer die Serien-Suchanfrage entfernen.
    # Neben S01E02 und 1x02 werden auch Release-Schemata wie E02S01 sowie
    # EP02 erkannt. EPxx enthaelt absichtlich keine Staffel; diese wird im
    # Renamer vor der Metadatensuche interaktiv nachgefragt.
    text = re.sub(
        r"(?<!\w)S\s*\d{1,4}[.\-_\s]*E\s*\d{1,4}(?:[.\-_\s]*E?\s*\d{1,4})*(?!\d).*$",
        "", text, flags=re.I,
    )
    text = re.sub(
        r"(?<!\w)E\s*\d{1,4}[.\-_\s]*S\s*\d{1,4}(?!\d).*$",
        "", text, flags=re.I,
    )
    text = re.sub(r"(?<!\w)EP(?:ISODE)?[.\-_\s]*\d{1,4}(?!\d).*$", "", text, flags=re.I)
    # Manche Release-Namen enthalten nur E19 statt S01E19/EP19. Der Renamer
    # behandelt diese Form als Episode der standardmaessigen Staffel 1; fuer
    # die Provider-Suche muss der Episodenmarker trotzdem aus dem Titel raus.
    text = re.sub(r"(?<!\w)E\s*\d{1,4}(?!\d).*$", "", text, flags=re.I)
    text = re.sub(r"\b\d{1,4}x\d{1,4}\b.*$", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip()

    year, m = _extract_metadata_year(text)
    if m is not None:
        text = text[: m.start()].strip(" -._")

    # Ab dem ERSTEN technischen Release-Marker wird der Rest abgeschnitten.
    # Dadurch wird z. B.
    #   tvs-watson-eac3-51-ded-dl-18p-azhd-avc
    # sauber zu "watson" statt zum kompletten Release-String.
    release_marker_re = re.compile(
        r"\b(?:"
        # Sprache / Dub / Sub
        r"German|Deutsch|Ger|Deu|Eng|DED|SED|DL|Dual|Subbed|Sub|Dubbed|MULTI|"
        # Quelle / Provider
        r"WEB(?:[- ]?DL)?|WEBRip|BluRay|BDRip|BRRip|HDTV|DVD|Remux|AmazonHD|AZHD|AMZN|"
        # Aufloesung
        r"UHD|4320p|2160p|1440p|1080p|720p|576p|480p|18p|"
        # HDR
        r"HDR|DV|DoVi|HDR10(?:Plus)?|HLG|"
        # Audio
        r"AAC|EAC3|E-AC3|AC3|DDP|DD(?:20|51|71)?|DTS(?:HD)?|TrueHD|Atmos|FLAC|MP3|"
        # Video
        r"H264|H265|HEVC|AVC|AV1|x264|x265|MPEG2|MPEG4|"
        # Sonstiges
        r"ANiME"
        r")\b",
        flags=re.I,
    )

    marker = release_marker_re.search(text)
    had_release_marker = marker is not None
    if marker:
        text = text[: marker.start()].strip(" -._")

    # "tvs-" ist in diesem alten TVS-Release-Schema die Release-Gruppe und
    # kein Teil des Serientitels. Nur entfernen, wenn vorher wirklich ein
    # technischer Release-Marker erkannt wurde; so bleiben echte Titel mit
    # "TVS" am Anfang unangetastet.
    if had_release_marker:
        text = re.sub(r"^tvs[-_.\s]+(?=\S)", "", text, flags=re.I)

    # Verbleibende Release-Trenner fuer die Metadatensuche normalisieren.
    text = re.sub(r"[-_.]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    return ParsedSeriesQuery(title=text or _metadata_input_stem(value)[1], year=year)


def clean_tmdb_collection_name(value: str) -> str:
    """Entfernt reine Provider-Suffixe aus TMDB-Collection-Namen.

    TMDB lokalisiert Collections oft als "Titel Filmreihe" oder "Title
    Collection". Für DragonTools-Zielordner ist der reine Reihenname sinnvoller.
    """
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    cleaned = re.sub(
        r"\s*(?:[-–—:]\s*)?(?:Filmreihe|Collection|Sammlung|Kollektion)\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip(" -–—:")
    return cleaned or text

class ParsedMetadataResolverMixin:
    """Gemeinsame Dateiname→Resolver-Brücke für TMDB, TVDB und Composite-Client."""

    def resolve_movie_file(self, path: str | Path) -> MovieMetadataSuggestion | None:
        parsed = parse_movie_query(path)
        if not parsed.title:
            return None
        return self.resolve_movie(parsed.title, year=parsed.year)

    def resolve_series_name(self, value: str | Path) -> SeriesMetadataSuggestion | None:
        parsed = parse_series_query(value)
        if not parsed.title:
            return None
        return self.resolve_series(parsed.title, year=parsed.year)

def compare_metadata_text(value: str) -> str:
    """Unicode-safe comparison key for provider titles and cache identity.

    Provider names can be Japanese, Chinese, Cyrillic, etc.  Restricting the key
    to ASCII/Latin characters collapses such titles to an empty string and makes
    unrelated non-Latin records score as identical/no-match.
    """
    text = unicodedata.normalize("NFKC", fold_german_umlauts(value)).casefold()
    text = text.replace("&", " und ")
    text = "".join(ch if ch.isalnum() else " " for ch in text)
    return re.sub(r"\s+", " ", text).strip()
