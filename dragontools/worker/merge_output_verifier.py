# -*- coding: utf-8 -*-
"""Fail-closed verification for lossless merge outputs."""
from __future__ import annotations

from dataclasses import dataclass

from .output_verifier import OutputVerifier


@dataclass(frozen=True, slots=True)
class MergeVerification:
    ok: bool
    messages: tuple[str, ...]


class MergeOutputVerifier:
    def __init__(self, *, ffprobe_path: str) -> None:
        self._verifier = OutputVerifier(
            ffprobe_path=ffprobe_path,
            min_size_bytes=1024,
            duration_min_ratio=0.97,
            duration_max_ratio=1.05,
            duration_max_extra_s=15.0,
        )

    def verify(
        self,
        *,
        output_path: str,
        expected_duration_ms: int | None,
        expected_audio_tracks: int,
        expected_subtitle_tracks: int,
    ) -> MergeVerification:
        result = self._verifier.verify(
            output_path,
            "mkv",
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
        return MergeVerification(
            ok=bool(
                result.ok
                and result.audio_stream_count == expected_audio_tracks
                and result.subtitle_stream_count == expected_subtitle_tracks
            ),
            messages=tuple(messages),
        )


__all__ = ["MergeVerification", "MergeOutputVerifier"]
