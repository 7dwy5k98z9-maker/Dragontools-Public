# -*- coding: utf-8 -*-
from __future__ import annotations

from ..core.lang_codes import language_aliases, language_matches
from ..core.models import AudioStream, SubtitleStream
from .subtitle_rule_config import (
    COMPATIBLE_SUBTITLE_CODECS,
    DEFAULT_PREFERRED_SUBTITLE_FORMATS,
    ENGLISH_LANGUAGE_CODES,
    GERMAN_LANGUAGE_CODES,
)


def normalized_language_set(raw_values, default: set[str]) -> set[str]:
    if isinstance(raw_values, str):
        values = {part.strip().lower() for chunk in raw_values.replace(";", "\n").splitlines() for part in chunk.split(",") if part.strip()}
    elif isinstance(raw_values, (list, tuple, set)):
        values = {str(value).strip().lower() for value in raw_values if str(value).strip()}
    else:
        values = set()
    expanded: set[str] = set()
    for value in values:
        expanded |= language_aliases(value) or {value}
    return expanded or set(default)


def preferred_languages(rules: dict | None, preferred_language: str = "de") -> set[str]:
    langs = normalized_language_set((rules or {}).get("preferred_languages", [preferred_language]), GERMAN_LANGUAGE_CODES)
    if langs & GERMAN_LANGUAGE_CODES:
        langs |= GERMAN_LANGUAGE_CODES
    return langs


def fallback_languages(rules: dict | None) -> set[str]:
    langs = normalized_language_set((rules or {}).get("fallback_languages", ["en", "eng"]), ENGLISH_LANGUAGE_CODES)
    if langs & ENGLISH_LANGUAGE_CODES:
        langs |= ENGLISH_LANGUAGE_CODES
    return langs


def expand_preferred_formats(values: list[str]) -> list[str]:
    expanded: list[str] = []
    def add(fmt: str) -> None:
        fmt = (fmt or "").strip().lower()
        if fmt and fmt not in expanded:
            expanded.append(fmt)
    for value in values:
        fmt = str(value or "").strip().lower()
        if not fmt:
            continue
        aliases = {
            "subrip": ("subrip", "srt"), "srt": ("subrip", "srt"),
            "ass": ("ass", "ssa"), "ssa": ("ass", "ssa"),
            "mov_text": ("mov_text", "tx3g"), "tx3g": ("mov_text", "tx3g"),
            "webvtt": ("webvtt",), "vtt": ("webvtt",),
            "pgs": ("hdmv_pgs_subtitle",), "sup": ("hdmv_pgs_subtitle",), "hdmv_pgs_subtitle": ("hdmv_pgs_subtitle",),
            "dvd_subtitle": ("dvd_subtitle", "vobsub"), "vobsub": ("dvd_subtitle", "vobsub"),
        }
        for candidate in aliases.get(fmt, (fmt,)):
            add(candidate)
    return expanded or list(DEFAULT_PREFERRED_SUBTITLE_FORMATS)


def preferred_formats(rules: dict | None) -> list[str]:
    raw = (rules or {}).get("preferred_formats", DEFAULT_PREFERRED_SUBTITLE_FORMATS)
    if isinstance(raw, str):
        values = [part.strip() for chunk in raw.replace(";", "\n").splitlines() for part in chunk.split(",") if part.strip()]
    elif isinstance(raw, (list, tuple, set)):
        values = [str(value).strip() for value in raw if str(value).strip()]
    else:
        values = list(DEFAULT_PREFERRED_SUBTITLE_FORMATS)
    return expand_preferred_formats(values)


def compatible_subtitles(streams: list[SubtitleStream]) -> list[SubtitleStream]:
    return [stream for stream in streams if (stream.codec or "").lower() in COMPATIBLE_SUBTITLE_CODECS]


def sort_by_preferred_formats(streams: list[SubtitleStream], formats: list[str]) -> list[SubtitleStream]:
    if not formats:
        return list(streams)
    order = {fmt.strip().lower(): i for i, fmt in enumerate(formats)}
    return sorted(streams, key=lambda stream: (order.get((stream.codec or "").lower(), len(formats)), int(stream.index)))


def best_format_tie_group(streams: list[SubtitleStream], formats: list[str]) -> list[SubtitleStream]:
    if not streams:
        return []
    order = {fmt.strip().lower(): i for i, fmt in enumerate(formats)}
    fallback_rank = len(formats)
    best_rank = min(order.get((stream.codec or "").lower(), fallback_rank) for stream in streams)
    return [stream for stream in streams if order.get((stream.codec or "").lower(), fallback_rank) == best_rank]


def has_german_audio(audio_streams: list[AudioStream] | None) -> bool:
    return bool(audio_streams) and any(language_matches(stream.language, "de") for stream in audio_streams)


def has_audio_language(audio_streams: list[AudioStream] | None, language: str) -> bool:
    return bool(audio_streams) and any(language_matches(stream.language, language) for stream in audio_streams)


def build_custom_track_map(ov: dict) -> dict[int, dict]:
    return {int(entry["index"]): dict(entry) for entry in list(ov.get("subtitle_tracks", []) or [])}


def match_by_language(streams: list[SubtitleStream], languages: set[str]) -> list[SubtitleStream]:
    return [stream for stream in streams if any(language_matches(stream.language, language) for language in languages)]


def dedupe_streams(streams: list[SubtitleStream]) -> list[SubtitleStream]:
    seen: set[int] = set()
    unique: list[SubtitleStream] = []
    for stream in streams:
        idx = int(stream.index)
        if idx not in seen:
            unique.append(stream)
            seen.add(idx)
    return unique


def language_rank(stream: SubtitleStream, language_priority: list[str]) -> int:
    for rank, language in enumerate(language_priority):
        if language_matches(stream.language, language):
            return rank
    return len(language_priority)


__all__ = [name for name in globals() if not name.startswith("_")]
