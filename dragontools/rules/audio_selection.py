# -*- coding: utf-8 -*-
"""Language-aware audio stream selection policy."""
from __future__ import annotations

from typing import Any

from ..core.lang_codes import language_matches, normalize_language_priority
from ..core.models import AudioStream
from .audio_rule_basics import _DEFAULT_RULES, normalize_audio_codec, safe_int
from .audio_rule_migration import migrate_audio_rules
from .audio_rule_repository import _load_rules

_COMMENTARY_MARKERS = (
    "commentary", "comment", "director", "regisseur", "kommentar",
    "audiokommentar", "audio commentary",
)

_DESCRIPTIVE_MARKERS = (
    "descriptive", "description", "audiodescription", "audio description",
    "audiodeskription", "hörfilm", "hoerfilm", "barrierefrei",
)

_AUDIO_CODEC_RANK = {
    "truehd": 0,
    "dts-hd ma": 1,
    "dts-hd hra": 2,
    "dts": 3,
    "flac": 4,
    "pcm": 5,
    "eac3": 6,
    "ac3": 7,
    "aac": 8,
    "mp3": 9,
    "mp2": 10,
}

def _stream_text(stream: AudioStream) -> str:
    return " ".join(
        str(value).strip().lower()
        for value in (getattr(stream, "title", None), getattr(stream, "language", None))
        if str(value or "").strip()
    )


def _has_any_marker(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _should_skip_for_language_rules(stream: AudioStream, rules: dict[str, Any]) -> bool:
    text = _stream_text(stream)
    if rules.get("ignore_commentary_tracks", True) and _has_any_marker(text, _COMMENTARY_MARKERS):
        return True
    if rules.get("ignore_descriptive_audio", True) and _has_any_marker(text, _DESCRIPTIVE_MARKERS):
        return True
    return False


def _sort_audio_candidates(streams: list[AudioStream]) -> list[AudioStream]:
    return sorted(
        streams,
        key=lambda stream: (
            -safe_int(getattr(stream, "channels", 0), 0),
            -safe_int(getattr(stream, "bitrate", 0), 0),
            _AUDIO_CODEC_RANK.get(normalize_audio_codec(getattr(stream, "codec", "")), 50),
            int(getattr(stream, "index", 0)),
        ),
    )


def _dedupe_audio_streams(streams: list[AudioStream]) -> list[AudioStream]:
    seen: set[int] = set()
    unique: list[AudioStream] = []
    for stream in streams:
        idx = int(getattr(stream, "index", len(seen)))
        if idx in seen:
            continue
        unique.append(stream)
        seen.add(idx)
    return unique


def _fallback_audio_streams(
    streams: list[AudioStream],
    eligible_streams: list[AudioStream],
    rules: dict[str, Any],
) -> list[AudioStream]:
    policy = str(rules.get("fallback_if_no_priority_match", "keep_all")).strip().lower()
    fallback_pool = eligible_streams or streams
    if policy == "keep_none":
        return []
    if policy == "keep_first":
        return fallback_pool[:1]
    return list(fallback_pool)


def choose_audio_stream(
    streams: list[AudioStream],
    rules: dict | None = None,
) -> AudioStream | None:
    """Wählt die beste Audio-Spur nach Sprach-Präferenz (erste Spur, Single-Track API)."""
    result = choose_audio_streams(streams, rules)
    return result[0] if result else None


def choose_audio_streams(
    streams: list[AudioStream],
    rules: dict | None = None,
) -> list[AudioStream]:
    """
    Wählt Audio-Spuren nach der klickbaren Sprach-Priorität aus.

    max_languages begrenzt die Anzahl der Sprachgruppen, tracks_per_language
    die Spuren je Sprache. Alte preferred/fallback/max_tracks-Regeln werden
    vorher in dieses Schema migriert.
    """
    if not streams:
        return []

    if rules is None:
        rules = _load_rules()
    else:
        rules = migrate_audio_rules(rules)

    priority = normalize_language_priority(rules.get("language_priority")) or list(_DEFAULT_RULES["language_priority"])
    max_languages = max(0, safe_int(rules.get("max_languages", rules.get("max_tracks", 1)), 1))
    tracks_per_language = max(0, safe_int(rules.get("tracks_per_language", 1), 1))
    eligible_streams = [
        stream for stream in streams
        if not _should_skip_for_language_rules(stream, rules)
    ]
    if not eligible_streams:
        eligible_streams = list(streams)

    selected: list[AudioStream] = []
    seen_indices: set[int] = set()

    def _add(s: AudioStream) -> None:
        if s.index in seen_indices:
            return
        selected.append(s)
        seen_indices.add(s.index)

    matched_languages = 0
    for lang in priority:
        matches = [
            stream for stream in eligible_streams
            if language_matches(getattr(stream, "language", None), lang)
        ]
        if not matches:
            continue

        matched_languages += 1
        limit = None if tracks_per_language == 0 else tracks_per_language
        for stream in _sort_audio_candidates(matches)[:limit]:
            _add(stream)

        if max_languages > 0 and matched_languages >= max_languages:
            break

    if not selected:
        return _dedupe_audio_streams(_fallback_audio_streams(streams, eligible_streams, rules))

    return _dedupe_audio_streams(selected)
