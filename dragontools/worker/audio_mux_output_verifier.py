# -*- coding: utf-8 -*-
"""Fail-closed verification for AudioMux outputs before commit."""
from __future__ import annotations

from dataclasses import dataclass

from .media_contract_types import ExpectedMediaContract
from .output_verifier import OutputVerifier


@dataclass(frozen=True, slots=True)
class AudioMuxVerification:
    ok: bool
    messages: tuple[str, ...]


class AudioMuxOutputVerifier:
    def __init__(self, *, ffprobe_path: str) -> None:
        self._verifier = OutputVerifier(ffprobe_path=ffprobe_path, min_size_bytes=1024)

    def verify(
        self, *, output_path: str, expected_duration_ms: int | None,
        expected_audio_tracks: int | None = None,
        expected_contract: ExpectedMediaContract | None = None,
    ) -> AudioMuxVerification:
        count = expected_contract.audio_stream_count if expected_contract is not None else int(expected_audio_tracks or 0)
        result = self._verifier.verify(
            output_path,
            "mkv",
            expected_duration_ms=expected_duration_ms,
            source_has_audio=count > 0,
            expected_contract=expected_contract,
        )
        messages = list(result.messages or [])
        if expected_contract is None and result.audio_stream_count != count:
            messages.append(
                f"Audiospur-Anzahl abweichend: erwartet {count}, gefunden {result.audio_stream_count}."
            )
        ok = bool(result.ok and (expected_contract is not None or result.audio_stream_count == count))
        return AudioMuxVerification(ok=ok, messages=tuple(messages))
