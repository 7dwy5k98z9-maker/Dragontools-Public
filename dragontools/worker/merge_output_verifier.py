# -*- coding: utf-8 -*-
"""Fail-closed verification for lossless merge outputs."""
from __future__ import annotations

from dataclasses import dataclass

from .output_verifier import OutputVerifier
from .media_contract_types import ExpectedMediaContract


@dataclass(frozen=True, slots=True)
class MergeVerification:
    ok: bool
    messages: tuple[str, ...]


class MergeOutputVerifier:
    def __init__(self, *, ffprobe_path: str, worker=None) -> None:
        self._verifier = OutputVerifier(
            worker=worker,
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
        expected_video_tracks: int = 1,
        expected_contract: ExpectedMediaContract | None = None,
        expected_chapter_count: int | None = None,
    ) -> MergeVerification:
        result = self._verifier.verify(
            output_path,
            "mkv",
            expected_duration_ms=expected_duration_ms,
            source_has_audio=expected_audio_tracks > 0,
            expected_contract=expected_contract,
        )
        messages = list(result.messages or [])
        if expected_chapter_count is not None and result.chapter_count != expected_chapter_count:
            messages.append(
                f"Kapitel-Anzahl abweichend: erwartet {expected_chapter_count}, gefunden {result.chapter_count}."
            )
        if result.video_stream_count != expected_video_tracks:
            messages.append(
                f"Videospur-Anzahl abweichend: erwartet {expected_video_tracks}, "
                f"gefunden {result.video_stream_count}."
            )
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
                and (expected_chapter_count is None or result.chapter_count == expected_chapter_count)
                and result.video_stream_count == expected_video_tracks
                and result.audio_stream_count == expected_audio_tracks
                and result.subtitle_stream_count == expected_subtitle_tracks
            ),
            messages=tuple(messages),
        )


__all__ = ["MergeVerification", "MergeOutputVerifier"]
