# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .duration_packet_integrity import PacketIntegrityVerifier
from .duration_repair_models import MediaTimingInfo, calculate_expected_duration
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
        self._packet_integrity = PacketIntegrityVerifier(
            ffprobe_path=getattr(runtime, "ffprobe_path", ""),
            run_tool=runtime.run_tool,
        )

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
        before_mkvmerge=None,
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
            before_mkvmerge=before_mkvmerge,
            candidate_path=str(path),
            expected_contract=expected_contract,
        )
        for message in guard.messages:
            level = "warn" if guard.ok else "error"
            self._runtime.log(f"{'⚠️' if guard.ok else '❌'} Stream-Gegenprüfung: {message}", level)

        # Stream-Anzahlen werden bei Reparaturkandidaten durch den 3-Tool-Guard
        # beurteilt. So darf z. B. ein MediaInfo-Parserfehler mit V=0/A=0/S=0
        # einen von ffprobe/MKVToolNix bestätigten Stream nicht verwerfen.
        stream_overrides = set(getattr(guard, "confirmed_kinds", set()) or set())
        ok, messages = validate_timestamp_repair(
            before=before,
            repaired=repaired_info,
            verify_result=verify_result,
            expected_duration_ms=expected_duration_ms,
            source_has_audio=source_has_audio,
            stream_count_overrides=stream_overrides,
            ignore_verify_stream_kinds=stream_overrides,
        )
        all_messages = list(messages)
        if not guard.ok:
            all_messages.extend(message for message in guard.messages if message not in all_messages)

        # Die Reparatur ist lossless. Daher müssen Paketanzahl und Paketnutzdaten
        # pro Stream bitidentisch bleiben; nur Container-/Paketzeitstempel dürfen
        # sich ändern. Diese Prüfung schützt die bewusst tolerantere Laufzeitlogik.
        reference_duration_s = (
            float(expected_duration_ms) / 1000.0
            if expected_duration_ms and expected_duration_ms > 0
            else calculate_expected_duration(repaired_info) or calculate_expected_duration(before)
        )
        packet_result = self._packet_integrity.validate(
            before.path,
            str(path),
            reference_duration_s=reference_duration_s,
            frame_rate=repaired_info.frame_rate or before.frame_rate,
            tolerance_s=0.4,
        )
        if not packet_result.ok:
            all_messages.extend(message for message in packet_result.messages if message not in all_messages)
        elif packet_result.available:
            self._runtime.log(
                "✅ Paketprüfung: Stream-Paketanzahl und SHA-256-Nutzdaten pro Stream unverändert.",
                "info",
            )
        else:
            for message in packet_result.messages:
                self._runtime.log(f"⚠️ {message}", "warn")

        return CandidateValidation(
            ok=bool(ok and guard.ok and packet_result.ok),
            repaired_info=repaired_info,
            verify_result=verify_result,
            messages=all_messages,
        )

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
