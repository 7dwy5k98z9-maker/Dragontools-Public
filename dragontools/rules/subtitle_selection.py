# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from ..core.lang_codes import language_aliases, language_matches, normalize_language_priority
from ..core.models import AudioStream, SubtitleStream
from ..core.type_utils import _safe_bool
from .subtitle_rule_config import (
    COMPATIBLE_SUBTITLE_CODECS,
    DEFAULT_PREFERRED_SUBTITLE_FORMATS,
    ENGLISH_LANGUAGE_CODES,
    GERMAN_LANGUAGE_CODES,
    safe_int as _safe_int,
)

def _normalized_language_set(raw_values, default: set[str]) -> set[str]:
    if isinstance(raw_values, str):
        values = {
            part.strip().lower()
            for chunk in raw_values.replace(";", "\n").splitlines()
            for part in chunk.split(",")
            if part.strip()
        }
    elif isinstance(raw_values, (list, tuple, set)):
        values = {str(value).strip().lower() for value in raw_values if str(value).strip()}
    else:
        values = set()
    expanded: set[str] = set()
    for value in values:
        expanded |= language_aliases(value) or {value}
    return expanded or set(default)


def _preferred_languages(rules: dict | None, preferred_language: str = "de") -> set[str]:
    raw_langs = (rules or {}).get("preferred_languages", [preferred_language])
    pref_langs = _normalized_language_set(raw_langs, GERMAN_LANGUAGE_CODES)
    if pref_langs & GERMAN_LANGUAGE_CODES:
        pref_langs |= GERMAN_LANGUAGE_CODES
    return pref_langs


def _fallback_languages(rules: dict | None) -> set[str]:
    raw_langs = (rules or {}).get("fallback_languages", ["en", "eng"])
    fallback_langs = _normalized_language_set(raw_langs, ENGLISH_LANGUAGE_CODES)
    if fallback_langs & ENGLISH_LANGUAGE_CODES:
        fallback_langs |= ENGLISH_LANGUAGE_CODES
    return fallback_langs


def _expand_preferred_formats(values: list[str]) -> list[str]:
    expanded: list[str] = []

    def add(fmt: str) -> None:
        fmt = (fmt or "").strip().lower()
        if fmt and fmt not in expanded:
            expanded.append(fmt)

    for value in values:
        fmt = str(value or "").strip().lower()
        if not fmt:
            continue
        if fmt in {"subrip", "srt"}:
            add("subrip")
            add("srt")
        elif fmt in {"ass", "ssa"}:
            add("ass")
            add("ssa")
        elif fmt in {"mov_text", "tx3g"}:
            add("mov_text")
            add("tx3g")
        elif fmt in {"webvtt", "vtt"}:
            add("webvtt")
        elif fmt in {"pgs", "sup", "hdmv_pgs_subtitle"}:
            add("hdmv_pgs_subtitle")
        elif fmt in {"dvd_subtitle", "vobsub"}:
            add("dvd_subtitle")
            add("vobsub")
        else:
            add(fmt)
    return expanded or list(DEFAULT_PREFERRED_SUBTITLE_FORMATS)


def _preferred_formats(rules: dict | None) -> list[str]:
    raw = (rules or {}).get("preferred_formats", DEFAULT_PREFERRED_SUBTITLE_FORMATS)
    if isinstance(raw, str):
        values = [
            part.strip()
            for chunk in raw.replace(";", "\n").splitlines()
            for part in chunk.split(",")
            if part.strip()
        ]
    elif isinstance(raw, (list, tuple, set)):
        values = [str(value).strip() for value in raw if str(value).strip()]
    else:
        values = list(DEFAULT_PREFERRED_SUBTITLE_FORMATS)
    return _expand_preferred_formats(values)


def _compatible_subtitles(streams: list[SubtitleStream]) -> list[SubtitleStream]:
    return [
        stream for stream in streams
        if (stream.codec or "").lower() in COMPATIBLE_SUBTITLE_CODECS
    ]


def _sort_by_preferred_formats(
    streams: list[SubtitleStream],
    preferred_formats: list[str],
) -> list[SubtitleStream]:
    if not preferred_formats:
        return list(streams)
    order = {fmt.strip().lower(): i for i, fmt in enumerate(preferred_formats)}
    return sorted(
        streams,
        key=lambda stream: (
            order.get((stream.codec or "").lower(), len(preferred_formats)),
            int(stream.index),
        ),
    )


def _best_format_tie_group(
    streams: list[SubtitleStream],
    preferred_formats: list[str],
) -> list[SubtitleStream]:
    if not streams:
        return []
    order = {fmt.strip().lower(): i for i, fmt in enumerate(preferred_formats)}
    fallback_rank = len(preferred_formats)
    best_rank = min(order.get((stream.codec or "").lower(), fallback_rank) for stream in streams)
    return [
        stream for stream in streams
        if order.get((stream.codec or "").lower(), fallback_rank) == best_rank
    ]


def _has_german_audio(audio_streams: list[AudioStream] | None) -> bool:
    if not audio_streams:
        return False
    return any(
        language_matches(stream.language, "de")
        for stream in audio_streams
    )


def _has_audio_language(audio_streams: list[AudioStream] | None, language: str) -> bool:
    if not audio_streams:
        return False
    return any(
        language_matches(stream.language, language)
        for stream in audio_streams
    )


def _build_custom_track_map(ov: dict) -> dict[int, dict]:
    return {
        int(entry["index"]): dict(entry)
        for entry in list(ov.get("subtitle_tracks", []) or [])
    }


def _match_by_language(
    streams: list[SubtitleStream],
    languages: set[str],
) -> list[SubtitleStream]:
    return [
        stream for stream in streams
        if any(language_matches(stream.language, language) for language in languages)
    ]


def _dedupe_streams(streams: list[SubtitleStream]) -> list[SubtitleStream]:
    seen: set[int] = set()
    unique: list[SubtitleStream] = []
    for stream in streams:
        idx = int(stream.index)
        if idx in seen:
            continue
        unique.append(stream)
        seen.add(idx)
    return unique


def _language_rank(stream: SubtitleStream, language_priority: list[str]) -> int:
    for rank, language in enumerate(language_priority):
        if language_matches(stream.language, language):
            return rank
    return len(language_priority)


def _fallback_subtitle_streams(
    streams: list[SubtitleStream],
    preferred_formats: list[str],
    rules: dict[str, Any],
) -> list[SubtitleStream]:
    policy = str(rules.get("fallback_if_no_priority_match", "keep_none")).strip().lower()
    if policy == "keep_all":
        return _sort_by_preferred_formats(streams, preferred_formats)
    if policy == "keep_first":
        ordered = _sort_by_preferred_formats(streams, preferred_formats)
        return ordered[:1]
    return []


def _select_subtitles_by_language_priority(
    streams: list[SubtitleStream],
    *,
    subtitle_rules: dict[str, Any],
    preferred_formats: list[str],
) -> list[SubtitleStream]:
    priority = normalize_language_priority(subtitle_rules.get("language_priority"))
    if not priority:
        return _fallback_subtitle_streams(streams, preferred_formats, subtitle_rules)

    max_languages = max(0, _safe_int(subtitle_rules.get("max_languages", 1), 1))
    tracks_per_language = max(0, _safe_int(subtitle_rules.get("tracks_per_language", 1), 1))
    chosen: list[SubtitleStream] = []
    matched_languages = 0

    for language in priority:
        matches = [
            stream for stream in streams
            if language_matches(stream.language, language)
        ]
        if not matches:
            continue

        matched_languages += 1
        ordered = _sort_by_preferred_formats(matches, preferred_formats)
        limit = None if tracks_per_language == 0 else tracks_per_language
        chosen.extend(ordered[:limit])

        if max_languages > 0 and matched_languages >= max_languages:
            break

    if not chosen:
        return _fallback_subtitle_streams(streams, preferred_formats, subtitle_rules)
    return _dedupe_streams(chosen)


def _sort_sidecar_candidates_by_rule(
    streams: list[SubtitleStream],
    preferred_formats: list[str],
    *,
    force_priority: bool,
) -> list[SubtitleStream]:
    format_order = {fmt.strip().lower(): i for i, fmt in enumerate(preferred_formats)}
    return sorted(
        _dedupe_streams(streams),
        key=lambda stream: (
            format_order.get((stream.codec or "").lower(), len(preferred_formats)),
            0 if (force_priority and bool(stream.forced)) else 1,
            int(stream.index),
        ),
    )


def _limit_external_sidecar_streams(
    streams: list[SubtitleStream],
    *,
    subtitle_rules: dict[str, Any],
) -> list[SubtitleStream]:
    streams = _dedupe_streams(streams)
    if not streams:
        return []

    preferred_formats = _preferred_formats(subtitle_rules)
    force_priority = _safe_bool(subtitle_rules.get("force_priority"), True)
    max_languages = max(0, _safe_int(subtitle_rules.get("max_languages", 1), 1))
    tracks_per_language = max(0, _safe_int(subtitle_rules.get("tracks_per_language", 1), 1))

    if max_languages == 0 and tracks_per_language == 0:
        return _sort_sidecar_candidates_by_rule(
            streams,
            preferred_formats,
            force_priority=force_priority,
        )

    priority = normalize_language_priority(subtitle_rules.get("language_priority"))
    if not priority:
        policy = str(subtitle_rules.get("fallback_if_no_priority_match", "keep_none")).strip().lower()
        ordered = _sort_sidecar_candidates_by_rule(
            streams,
            preferred_formats,
            force_priority=force_priority,
        )
        if policy == "keep_all":
            return ordered
        if policy == "keep_first":
            return ordered[:1]
        return []

    chosen: list[SubtitleStream] = []
    matched_languages = 0

    for language in priority:
        matches = [
            stream for stream in streams
            if language_matches(stream.language, language)
        ]
        if not matches:
            continue

        matched_languages += 1
        ordered = _sort_sidecar_candidates_by_rule(
            matches,
            preferred_formats,
            force_priority=force_priority,
        )
        limit = None if tracks_per_language == 0 else tracks_per_language
        chosen.extend(ordered[:limit])

        if max_languages > 0 and matched_languages >= max_languages:
            break

    if chosen:
        return _dedupe_streams(chosen)

    policy = str(subtitle_rules.get("fallback_if_no_priority_match", "keep_none")).strip().lower()
    ordered = _sort_sidecar_candidates_by_rule(
        streams,
        preferred_formats,
        force_priority=force_priority,
    )
    if policy == "keep_all":
        return ordered
    if policy == "keep_first":
        return ordered[:1]
    return []
