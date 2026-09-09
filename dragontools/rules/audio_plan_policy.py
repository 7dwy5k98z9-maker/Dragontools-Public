from __future__ import annotations

from typing import Any

from ..core.models import AudioStream
from .audio_rules import (
    audio_requires_transcode,
    choose_audio_streams,
    default_transcode_target,
    normalize_audio_codec,
    safe_int,
)


MP4_COMPATIBLE_AUDIO_CODECS: frozenset[str] = frozenset({"aac", "ac3", "eac3"})


def build_custom_track_map(
    override: dict[str, Any],
    *,
    audio_mode: str,
) -> dict[int, dict[str, Any]]:
    """Normalize per-track custom entries into a stream-index keyed mapping."""
    if audio_mode != "custom":
        return {}

    custom_track_map: dict[int, dict[str, Any]] = {}
    for entry in list(override.get("audio_tracks", []) or []):
        if not isinstance(entry, dict):
            continue
        try:
            custom_track_map[int(entry.get("index"))] = dict(entry)
        except (TypeError, ValueError, OverflowError):
            continue
    return custom_track_map


def select_streams_for_plan(
    audio_streams: list[AudioStream],
    rules: dict[str, Any],
    *,
    audio_mode: str,
    custom_track_map: dict[int, dict[str, Any]],
    apply_language_rules: bool,
) -> list[AudioStream]:
    """Select streams while preserving the precedence of custom track mapping."""
    if audio_mode == "custom" and custom_track_map:
        stream_map = {int(stream.index): stream for stream in audio_streams}
        return [
            stream_map[index]
            for index in custom_track_map
            if index in stream_map and custom_track_map[index].get("mode") != "drop"
        ]
    if apply_language_rules:
        return choose_audio_streams(audio_streams, rules)
    return list(audio_streams)


def resolve_track_transcode(
    stream: AudioStream,
    rules: dict[str, Any],
    *,
    container: str,
    audio_mode: str,
    legacy_action: str,
    custom_entry: dict[str, Any] | None,
) -> tuple[bool, dict[str, Any]]:
    """Resolve copy/transcode and raw target before processing filters are applied."""
    needs_transcode, target = audio_requires_transcode(stream, rules)
    source_codec = normalize_audio_codec(stream.codec)

    if container == "mp4" and source_codec not in MP4_COMPATIBLE_AUDIO_CODECS:
        needs_transcode, target = _default_transcode(stream, rules)

    if custom_entry and custom_entry.get("mode") == "custom":
        needs_transcode, target = _apply_custom_track_override(stream, custom_entry)
    elif audio_mode == "custom":
        needs_transcode, target = _apply_legacy_action(
            stream,
            rules,
            legacy_action=legacy_action,
            current_needs=needs_transcode,
            current_target=target,
        )

    # Final, non-overridable MP4 guard. A custom "copy" cannot bypass it.
    if container == "mp4" and not needs_transcode and source_codec not in MP4_COMPATIBLE_AUDIO_CODECS:
        needs_transcode, target = _default_transcode(stream, rules)

    return needs_transcode, target


def _apply_custom_track_override(
    stream: AudioStream,
    custom_entry: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    forced_codec = str(custom_entry.get("codec") or "copy").lower()
    forced_bitrate = safe_int(custom_entry.get("bitrate"), 0) or safe_int(stream.bitrate, 0)
    if forced_codec == "copy":
        return False, {
            "codec": "copy",
            "channels": stream.channels,
            "bitrate": stream.bitrate,
        }
    return True, {
        "codec": forced_codec,
        "channels": stream.channels,
        "bitrate": forced_bitrate,
    }


def _apply_legacy_action(
    stream: AudioStream,
    rules: dict[str, Any],
    *,
    legacy_action: str,
    current_needs: bool,
    current_target: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    if legacy_action == "copy":
        return False, {
            "codec": "copy",
            "channels": stream.channels,
            "bitrate": stream.bitrate,
        }
    if legacy_action == "eac3":
        _, target = _default_transcode(stream, rules)
        target["codec"] = "eac3"
        return True, target
    if legacy_action == "aac":
        return True, (
            {"codec": "aac", "channels": 2, "bitrate": 256000}
            if safe_int(stream.channels, 0) >= 2
            else {"codec": "aac", "channels": 1, "bitrate": 128000}
        )
    return current_needs, current_target


def default_target_for_stream(stream: AudioStream, rules: dict[str, Any]) -> dict[str, Any]:
    """Create the default transcode target for a stream."""
    return default_transcode_target(
        safe_int(stream.channels, 2),
        safe_int(stream.bitrate, 0),
        rules,
    )


def _default_transcode(
    stream: AudioStream,
    rules: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    return True, default_target_for_stream(stream, rules)
