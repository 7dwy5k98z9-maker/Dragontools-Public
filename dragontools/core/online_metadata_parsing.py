# -*- coding: utf-8 -*-
"""Dateiname→Metadaten-Suchanfrage und textuelle Normalisierung."""
from __future__ import annotations

import re
from pathlib import Path

from .online_metadata_types import (
    MovieMetadataSuggestion, ParsedMovieQuery, ParsedSeriesQuery, SeriesMetadataSuggestion,
)

def parse_movie_query(value: str | Path) -> ParsedMovieQuery:
    raw = str(value)
    path = Path(raw)
    video_exts = {".mkv", ".mp4", ".avi", ".m4v", ".mov", ".ts", ".m2ts", ".wmv"}
    text = path.stem if path.suffix.lower() in video_exts else raw
    text = re.sub(r"[_\s]?(H264|H265|AV1|HEVC|x265|x264)$", "", text, flags=re.I).strip()
    text = text.replace("_", " ").replace(".", " ")
    text = re.sub(r"\s+", " ", text).strip()

    year: int | None = None
    m = re.search(r"\((19\d{2}|20\d{2})\)", text)
    if not m:
        m = re.search(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)", text)
    if m:
        year = int(m.group(1))
        text = text[: m.start()].strip(" -._")

    cleanup_patterns = (
        r"\b(German|Deutsch|Ger|Eng|DL|Subbed|Sub|Dubbed|WEB|WEBRip|BluRay|BDRip|"
        r"UHD|2160p|1080p|720p|HDR|DV|DoVi|HDR10|HDR10Plus|AAC|EAC3|DTS|"
        r"H264|H265|HEVC|AVC|AV1|x264|x265)\b.*$"
    )
    text = re.sub(cleanup_patterns, "", text, flags=re.I).strip(" -._")
    text = re.sub(r"\s+", " ", text).strip()
    return ParsedMovieQuery(title=text or Path(str(value)).stem, year=year)


def parse_series_query(value: str | Path) -> ParsedSeriesQuery:
    # DragonTools patch: series release normalization v1
    raw = str(value)
    path = Path(raw)
    video_exts = {".mkv", ".mp4", ".avi", ".m4v", ".mov", ".ts", ".m2ts", ".wmv"}
    text = path.stem if path.suffix.lower() in video_exts else raw

    # Normale Trenner vereinheitlichen. Bindestriche bleiben zunaechst erhalten,
    # damit Scene-/Release-Schemata wie "tvs-watson-eac3-..." erkennbar bleiben.
    text = text.replace("_", " ").replace(".", " ")

    # Episodenmarker und alles dahinter fuer die Serien-Suchanfrage entfernen.
    text = re.sub(r"\bS\d{1,2}E\d{1,3}(?:[-_ ]?E?\d{1,3})*\b.*$", "", text, flags=re.I)
    text = re.sub(r"\b\d{1,2}x\d{1,3}\b.*$", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip()

    year: int | None = None
    m = re.search(r"\((19\d{2}|20\d{2})\)", text)
    if not m:
        m = re.search(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)", text)
    if m:
        year = int(m.group(1))
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

    return ParsedSeriesQuery(title=text or Path(str(value)).stem, year=year)


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
    text = str(value or "").lower()
    text = re.sub(r"[^a-z0-9äöüß]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()
