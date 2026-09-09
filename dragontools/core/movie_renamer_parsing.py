# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from pathlib import Path

from .movie_renamer_models import ParsedMovieReleaseName, ParsedSeriesReleaseName
from .online_metadata_common import default_episode_title, normalize_episode_metadata_title, parse_series_query
from .paths import path_compare_key
from ..rules.renamer_rules import sanitize_renamer_text

VIDEO_SUFFIXES = {
    ".mkv",
    ".mp4",
    ".avi",
    ".m4v",
    ".mov",
    ".ts",
    ".m2ts",
    ".mts",
    ".webm",
    ".wmv",
    ".flv",
    ".mpg",
    ".mpeg",
}


TECHNICAL_TAG_PATTERNS: tuple[tuple[str, str], ...] = (
    # DragonTools patch: series release normalization v1
    ("German", r"\b(?:German|Deutsch|Ger|Deu|DED|Dubbed)\b"),
    ("Dual Language", r"\b(?:DL|Dual(?:[ -]?Language)?|MULTI)\b"),
    ("Subbed", r"\b(?:Subbed|Subs?|Forced|SED|Synced)\b"),
    ("Auflösung", r"\b(?:4320p|2160p|1440p|1080p|720p|576p|480p|18p|UHD|HD)\b"),
    ("Quelle", r"\b(?:BluRay|BDRip|BRRip|WEB[- ]?DL|WEBRip|WEB|HDTV|DVDRip|DVD|Remux|AmazonHD|AZHD|AMZN)\b"),
    ("Video", r"\b(?:HEVC|H265|H\.265|AVC|H264|H\.264|x265|x264|AV1|MPEG2|MPEG4)\b"),
    ("HDR", r"\b(?:DV|DoVi|Dolby[ -]?Vision|HDR10\+?|HDR10Plus|HDR|HLG)\b"),
    ("Audio", r"\b(?:DTSHD|DTS[- ]?HD|DTS|TrueHD|Atmos|EAC3|E-AC3|AC3|DDP|DD(?:20|51|71)?|AAC|FLAC|MP3)\b"),
    ("Release", r"\b(?:PROPER|REPACK|REAL|INTERNAL|COMPLETE|GERMAN|MULTi|UNCUT)\b"),
    ("Anime", r"\b(?:ANiME|Anime)\b"),
)


EDITION_PATTERNS: tuple[tuple[str, str], ...] = (
    ("Director's Cut", r"\bDirectors?\s+Cut\b|\bDirector['’]s\s+Cut\b"),
    ("Extended Cut", r"\bExtended\s+Cut\b|\bExtended\b"),
    ("Unrated", r"\bUnrated\b"),
    ("Theatrical Cut", r"\bTheatrical\s+Cut\b|\bTheatrical\b"),
    ("Remastered", r"\bRemastered\b|\bRestored\b"),
    ("Ultimate Cut", r"\bUltimate\s+Cut\b"),
    ("Final Cut", r"\bFinal\s+Cut\b"),
    ("Uncut", r"\bUncut\b"),
)

_YEAR_RE = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")
_RELEASE_GROUP_RE = re.compile(r"-(?P<group>[A-Za-z0-9][A-Za-z0-9._]{1,32})$")
_SERIES_EPISODE_RE = re.compile(r"\bS\d{1,2}E\d{1,3}(?:[-_ ]?E?\d{1,3})*\b|\b\d{1,2}x\d{1,3}\b", re.IGNORECASE)

def _looks_like_series_release_group(stem: str, episode_marker: re.Match[str], group_match: re.Match[str]) -> bool:
    """Konservative Release-Gruppen-Erkennung fuer Serien.

    Ein einzelnes normales Wort am Ende eines Episodentitels (z. B.
    ``-Abschlussevent``) darf nicht als Scene-Gruppe gelten. Echte Gruppen
    werden weiterhin erkannt, wenn vor ihnen technische Release-Tags stehen
    oder der Gruppenname selbst klar release-typisch aussieht.
    """
    if group_match.start() < episode_marker.end():
        return False

    group = group_match.group("group").strip(".-_ ")
    if len(group) < 2:
        return False

    between = stem[episode_marker.end(): group_match.start()]
    normalized_between = _normalize_release_text(between)
    if _find_named_patterns(normalized_between, TECHNICAL_TAG_PATTERNS):
        return True

    letters = [ch for ch in group if ch.isalpha()]
    uppers = sum(ch.isupper() for ch in letters)
    lowers = sum(ch.islower() for ch in letters)

    # Klassische Scene-/P2P-Gruppen: GRP, NIMA4K, DETAiLS, SiXTYNiNE usw.
    if letters and lowers == 0 and uppers >= 2:
        return True
    if any(ch.isdigit() for ch in group) and uppers >= 1:
        return True
    if uppers >= 2 and lowers >= 1:
        return True
    if any(ch in "._" for ch in group) and uppers >= 1:
        return True

    return False

def parse_movie_release_name(value: str | Path) -> ParsedMovieReleaseName:
    source = Path(str(value))
    name = source.name
    suffix = source.suffix if source.suffix.lower() in VIDEO_SUFFIXES else ""
    stem = source.stem if suffix else str(value)
    is_probable_series = bool(_SERIES_EPISODE_RE.search(stem))
    release_group = ""
    group_match = _RELEASE_GROUP_RE.search(stem)
    if group_match:
        release_group = group_match.group("group").strip(".-_ ")
        stem = stem[: group_match.start()].strip(".-_ ")

    normalized = _normalize_release_text(stem)
    edition_hints = _find_named_patterns(normalized, EDITION_PATTERNS)
    technical_tags = _find_named_patterns(normalized, TECHNICAL_TAG_PATTERNS)

    year: int | None = None
    year_match = _YEAR_RE.search(normalized)
    title_text = normalized
    if year_match:
        year = int(year_match.group(1))
        title_text = normalized[: year_match.start()]
    else:
        title_text = _strip_named_patterns(title_text, EDITION_PATTERNS)
        title_text = _strip_named_patterns(title_text, TECHNICAL_TAG_PATTERNS)

    query_title = _cleanup_title(title_text)
    warnings: list[str] = []
    if not query_title:
        query_title = _cleanup_title(normalized) or source.stem
        warnings.append("Suchname konnte nur grob aus dem Dateinamen abgeleitet werden.")
    if year is None:
        warnings.append("Kein Jahr im Dateinamen erkannt.")
    if edition_hints:
        warnings.append("Edition-Hinweis erkannt, wird nicht automatisch in den Zielnamen geschrieben.")
    if release_group:
        warnings.append(f"Release-Gruppe erkannt: {release_group}")
    if is_probable_series:
        warnings.append("Serienmuster erkannt.")

    return ParsedMovieReleaseName(
        source_name=name,
        suffix=suffix or source.suffix,
        query_title=query_title,
        year=year,
        is_probable_series=is_probable_series,
        release_group=release_group,
        edition_hints=edition_hints,
        technical_tags=technical_tags,
        warnings=tuple(warnings),
    )


def parse_series_release_name(value: str | Path) -> ParsedSeriesReleaseName | None:
    # DragonTools patch: series release normalization v1
    source = Path(str(value))
    suffix = source.suffix if source.suffix.lower() in VIDEO_SUFFIXES else source.suffix
    stem = source.stem if suffix else str(value)

    # Release-Gruppe bei Serien nur akzeptieren, wenn sie HINTER dem
    # Episodenmarker liegt. Sonst wird bei Namen wie
    # tvs-watson-eac3-51-ded-dl-18p-azhd-avc-s01e01
    # der technische Teil faelschlich als Release-Gruppe interpretiert.
    release_group = ""
    episode_marker = _SERIES_EPISODE_RE.search(stem)
    group_match = _RELEASE_GROUP_RE.search(stem)
    if (
        group_match
        and episode_marker
        and _looks_like_series_release_group(stem, episode_marker, group_match)
    ):
        release_group = group_match.group("group").strip(".-_ ")
        stem = stem[: group_match.start()].strip(".-_ ")

    try:
        from ..rules.move_rules import parse_series_match_details
    except Exception:
        parse_series_match_details = None

    details = parse_series_match_details(source.name) if parse_series_match_details else None
    if not details or not details.get("series"):
        return None

    # Die zentrale Metadaten-Normalisierung verwenden, statt den kompletten
    # Block vor SxxExx direkt als Serientitel zu uebernehmen.
    series_query = parse_series_query(source.name)
    series = series_query.title or str(details.get("series") or "").strip()
    season = int(details.get("season") or 0)
    episode = int(details.get("episode") or 0)

    match = _SERIES_EPISODE_RE.search(stem)
    episode_title = _cleanup_episode_title(stem[match.end():] if match else "")

    year: int | None = series_query.year
    if year is None:
        year_match = _YEAR_RE.search(stem)
        if year_match:
            year = int(year_match.group(1))

    technical_tags = _find_named_patterns(_normalize_release_text(stem), TECHNICAL_TAG_PATTERNS)
    warnings: list[str] = []
    if release_group:
        warnings.append(f"Release-Gruppe erkannt: {release_group}")
    if not episode_title:
        warnings.append("Kein lokaler Episodentitel im Dateinamen erkannt.")

    return ParsedSeriesReleaseName(
        source_name=source.name,
        suffix=suffix,
        series=series,
        season=season,
        episode=episode,
        episode_title=episode_title,
        year=year,
        release_group=release_group,
        technical_tags=technical_tags,
        warnings=tuple(warnings),
    )

def release_style_warnings(value: str | Path) -> tuple[str, ...]:
    """Erkennt typische noch nicht normalisierte Release-Dateinamen.

    Die Funktion klassifiziert nur; sie benennt nichts um. Sie wird u. a. vom
    Preflight verwendet, um frühzeitig die Metadatensuche hervorzuheben.
    """
    source = Path(value)
    stem = source.stem
    warnings: list[str] = []
    separators = re.findall(r"(?<=[A-Za-z0-9])[._](?=[A-Za-z0-9])", stem)
    if len(separators) >= 2:
        warnings.append("Release-Trenner (Punkte/Unterstriche) erkannt")
    parsed_series = parse_series_release_name(source)
    if parsed_series is not None:
        if parsed_series.release_group:
            warnings.append(f"Release-Gruppe: {parsed_series.release_group}")
        if parsed_series.technical_tags:
            warnings.append("Technik-Tags: " + ", ".join(parsed_series.technical_tags[:4]))
    else:
        parsed_movie = parse_movie_release_name(source)
        if parsed_movie.release_group:
            warnings.append(f"Release-Gruppe: {parsed_movie.release_group}")
        if parsed_movie.technical_tags:
            warnings.append("Technik-Tags: " + ", ".join(parsed_movie.technical_tags[:4]))
    return tuple(dict.fromkeys(warnings))

def build_target_filename(title: str, year: int | None, suffix: str) -> str:
    safe_title = sanitize_filename_part(title).strip()
    if year:
        base = f"{safe_title} ({int(year)})"
    else:
        base = safe_title
    clean_suffix = suffix if suffix.startswith(".") else f".{suffix}" if suffix else ""
    return f"{base}{clean_suffix}"


def build_series_target_filename(series: str, season: int, episode: int, episode_title: str, suffix: str) -> str:
    # Ein offizieller Serientitel darf auf einen Punkt enden (z. B. "Magilumiere Inc.").
    # Der Punkt liegt im fertigen Dateinamen vor " - SxxExx" und ist damit unter Windows
    # kein verbotener abschließender Punkt des Dateinamens.
    safe_series = sanitize_filename_part(series, fallback="Serie", preserve_trailing_period=True)
    ep = f"S{int(season):02d}E{int(episode):02d}"
    normalized_title, _is_fallback = normalize_episode_metadata_title(episode_title, episode)
    title = sanitize_filename_part(normalized_title, fallback=default_episode_title(episode))
    base = f"{safe_series} - {ep}"
    if title:
        base += f" - {title}"
    clean_suffix = suffix if suffix.startswith(".") else f".{suffix}" if suffix else ""
    return f"{base}{clean_suffix}"


def sanitize_filename_part(
    value: str,
    *,
    fallback: str = "Film",
    preserve_trailing_period: bool = False,
) -> str:
    # Zentraler Renamer-Sanitizer: dieselben konfigurierten Zeichenregeln werden
    # auch von Preflight/Online-Metadaten verwendet.
    return sanitize_renamer_text(
        value,
        fallback=fallback,
        preserve_trailing_period=preserve_trailing_period,
    )


def _cleanup_episode_title(value: str) -> str:
    text = str(value or "")
    text = re.sub(r"[\[\]{}()]", " ", text)
    text = text.replace("_", " ")
    text = re.sub(r"^[\s._:;,-]+", " ", text)
    text = re.sub(r"\s*[-–—]\s*", " ", text)
    text = re.sub(r"(?<=[A-Za-zÄÖÜäöüß])\.(?=[A-Za-zÄÖÜäöüß])", " ", text)
    text = re.sub(r"(?<=[A-Za-zÄÖÜäöüß])\.(?=\d)", " ", text)
    text = re.sub(r"(?<=\d)\.(?=[A-Za-zÄÖÜäöüß])", " ", text)
    text = _strip_named_patterns(text, TECHNICAL_TAG_PATTERNS)
    text = _strip_named_patterns(text, EDITION_PATTERNS)
    text = _YEAR_RE.sub(" ", text)
    text = re.sub(r"\b(?:Part|Pt)\s+(\d+)\b", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" .-_")
    return text


def rename_movie_file(source_path: str | Path, target_name: str) -> Path:
    source = Path(source_path)
    target = source.with_name(sanitize_filename_part(Path(target_name).stem) + Path(target_name).suffix)
    if path_compare_key(source) == path_compare_key(target):
        return source
    if target.exists():
        raise FileExistsError(f"Zieldatei existiert bereits: {target}")
    return source.rename(target)


def _normalize_release_text(value: str) -> str:
    text = str(value or "")
    text = re.sub(r"[\[\]{}()]", " ", text)
    text = text.replace("_", " ").replace(".", " ")
    text = re.sub(r"\s*[-–—]\s*", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _cleanup_title(value: str) -> str:
    text = _normalize_release_text(value)
    text = re.sub(r"\b(?:Part|Pt)\s+(\d+)\b", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" .-_")
    return text


def _find_named_patterns(value: str, patterns: tuple[tuple[str, str], ...]) -> tuple[str, ...]:
    found: list[str] = []
    for label, pattern in patterns:
        if re.search(pattern, value, flags=re.IGNORECASE):
            found.append(label)
    return tuple(dict.fromkeys(found))


def _strip_named_patterns(value: str, patterns: tuple[tuple[str, str], ...]) -> str:
    text = value
    for _label, pattern in patterns:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip(" .-_")
