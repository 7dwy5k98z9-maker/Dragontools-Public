# -*- coding: utf-8 -*-
"""Fail-closed verification for normal MP4 remux outputs."""
from __future__ import annotations

from dataclasses import dataclass

from .output_verifier import OutputVerifier


@dataclass(frozen=True, slots=True)
class MP4RemuxVerification:
    ok: bool
    messages: tuple[str, ...]


class MP4RemuxOutputVerifier:
    def __init__(self, *, ffprobe_path: str) -> None:
        self._verifier = OutputVerifier(ffprobe_path=ffprobe_path, min_size_bytes=1024)

    def verify(
        self,
        *,
        output_path: str,
        expected_duration_ms: int | None,
        expected_audio_tracks: int,
        expected_subtitle_tracks: int,
    ) -> MP4RemuxVerification:
        result = self._verifier.verify(
            output_path,
            "mp4",
            expected_duration_ms=expected_duration_ms,
            source_has_audio=expected_audio_tracks > 0,
        )
        messages = list(result.messages or [])
        if result.audio_stream_count != expected_audio_tracks:
            messages.append(
                f"Audiospur-Anzahl abweichend: erwartet {expected_audio_tracks}, "
                f"gefunden {result.audio_stream_count}."
            )
        if result.subtitle_stream_count != expected_subtitle_tracks:
            messages.append(
                f"Untertitelspur-Anzahl abweichend: erwartet {expected_subtitle_tracks}, "
                f"gefunden {result.subtitle_stream_count}."
            )
        ok = bool(
            result.ok
            and result.audio_stream_count == expected_audio_tracks
            and result.subtitle_stream_count == expected_subtitle_tracks
        )
        return MP4RemuxVerification(ok=ok, messages=tuple(messages))


__all__ = ["MP4RemuxVerification", "MP4RemuxOutputVerifier"]
