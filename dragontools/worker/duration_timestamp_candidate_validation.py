# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .duration_repair_models import MediaTimingInfo
from .duration_repair_validation import validate_timestamp_repair


@dataclass(slots=True)
class CandidateValidation:
    ok: bool
    repaired_info: MediaTimingInfo
    verify_result: object
    messages: list[str]


class TimestampCandidateValidator:
    def __init__(self, runtime, timing_analyzer, stream_guard) -> None:
        self._runtime = runtime
        self._timing_analyzer = timing_analyzer
        self._stream_guard = stream_guard

    def validate(
        self,
        path: Path,
        *,
        container: str,
        before: MediaTimingInfo,
        before_ffprobe,
        before_mediainfo,
        expected_duration_ms: int | None,
        source_has_audio: bool,
        expected_contract=None,
        verified_hdr10plus: bool = False,
        verified_dolby_vision: bool = False,
    ) -> CandidateValidation:
        repaired_info = self._timing_analyzer.get_media_timing_info(str(path))
        verify_result = self.verify_output(
            path,
            container=container,
            expected_duration_ms=expected_duration_ms,
            source_has_audio=source_has_audio,
            expected_contract=expected_contract,
            verified_hdr10plus=verified_hdr10plus,
            verified_dolby_vision=verified_dolby_vision,
        )
        guard = self._stream_guard.validate(
            before_ffprobe=before_ffprobe,
            before_mediainfo=before_mediainfo,
            candidate_path=str(path),
            expected_contract=expected_contract,
        )
        for message in guard.messages:
            level = "warn" if guard.ok else "error"
            self._runtime.log(f"{'⚠️' if guard.ok else '❌'} Stream-Gegenprüfung: {message}", level)
        ok, messages = validate_timestamp_repair(
            before=before,
            repaired=repaired_info,
            verify_result=verify_result,
            expected_duration_ms=expected_duration_ms,
            source_has_audio=source_has_audio,
            stream_count_overrides=set(),
        )
        all_messages = list(messages)
        if not guard.ok:
            all_messages.extend(message for message in guard.messages if message not in all_messages)
        return CandidateValidation(ok=bool(ok and guard.ok), repaired_info=repaired_info, verify_result=verify_result, messages=all_messages)

    def verify_output(self, path: Path, *, container: str, **kwargs):
        verify_kwargs = {
            "expected_duration_ms": kwargs["expected_duration_ms"],
            "source_has_audio": kwargs["source_has_audio"],
        }
        if kwargs.get("expected_contract") is not None:
            verify_kwargs["expected_contract"] = kwargs["expected_contract"]
        if kwargs.get("verified_hdr10plus"):
            verify_kwargs["verified_hdr10plus"] = True
        if kwargs.get("verified_dolby_vision"):
            verify_kwargs["verified_dolby_vision"] = True
        return self._runtime.output_verifier.verify(str(path), container, **verify_kwargs)
