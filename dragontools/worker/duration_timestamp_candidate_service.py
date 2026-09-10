# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from .duration_repair_models import MediaTimingInfo, TimestampRepairResult
from .duration_repair_validation import validate_timestamp_repair
from .duration_repair_stream_guard import RepairStreamGuard, StreamInventory


class TimestampCandidateService:
    """Führt einen einzelnen Timestamp-Reparaturkandidaten fail-closed aus."""

    def __init__(self, runtime, timing_analyzer, stream_guard: RepairStreamGuard) -> None:
        self._runtime = runtime
        self._timing_analyzer = timing_analyzer
        self._stream_guard = stream_guard

    def attempt(
        self,
        *,
        out: Path,
        tmp: Path,
        command: list[str],
        label: str,
        method: str,
        container: str,
        before: MediaTimingInfo,
        before_ffprobe: StreamInventory,
        before_mediainfo: StreamInventory,
        expected_duration_ms: int | None,
        source_has_audio: bool,
        timing_summary: list[str],
        expected_contract=None,
        verified_hdr10plus: bool = False,
        verified_dolby_vision: bool = False,
    ) -> TimestampRepairResult:
        run = self._runtime.run_tool(command, label=label)
        candidate_exists = self._candidate_plausible(out, tmp)
        if run.returncode != 0:
            tail = (run.stderr or run.stdout or "").strip().splitlines()
            detail = tail[-1] if tail else f"Returncode {run.returncode}"
            tolerated = method == "FFmpeg +genpts" and self._is_tolerated_genpts_returncode(
                run.returncode
            )
            if not candidate_exists or not tolerated:
                self._runtime.log(f"❌ {label} fehlgeschlagen: {detail}", "error")
                self._runtime.safe_unlink(tmp)
                return TimestampRepairResult(
                    attempted=True,
                    reason=f"{label} fehlgeschlagen: {detail}",
                    command=command,
                    timing_summary=timing_summary,
                    retry_recommended=True,
                    tool_returncode=run.returncode,
                    method=method,
                )
            self._runtime.log(
                f"⚠️ {label} endete mit Returncode {run.returncode}, hat aber eine Ausgabedatei erzeugt. "
                "Der Kandidat wird vollständig bis zum Dateiende geprüft.",
                "warn",
            )
            try:
                self._timing_analyzer.run_ffprobe_json(str(tmp), count_frames=True)
            except Exception as exc:
                self._runtime.log(
                    f"❌ Kandidat mit FFmpeg-EINVAL ist nicht vollständig lesbar: {exc}",
                    "error",
                )
                self._runtime.safe_unlink(tmp)
                return TimestampRepairResult(
                    attempted=True,
                    reason="FFmpeg-+genpts-Kandidat war nach EINVAL nicht vollständig lesbar.",
                    command=command,
                    timing_summary=timing_summary,
                    retry_recommended=True,
                    tool_returncode=run.returncode,
                    method=method,
                )

        if not candidate_exists:
            self._runtime.safe_unlink(tmp)
            return TimestampRepairResult(
                attempted=True,
                reason="Timestamp-Reparatur erzeugte keine plausible Ausgabedatei.",
                command=command,
                timing_summary=timing_summary,
                retry_recommended=True,
                tool_returncode=run.returncode,
                method=method,
            )

        repaired_info = self._timing_analyzer.get_media_timing_info(str(tmp))
        verify_result = self._verify_candidate(
            tmp,
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
            candidate_path=str(tmp),
            expected_contract=expected_contract,
        )
        for message in guard.messages:
            level = "warn" if guard.ok else "error"
            self._runtime.log(f"{'⚠️' if guard.ok else '❌'} Stream-Gegenprüfung: {message}", level)
        ok, validation_messages = validate_timestamp_repair(
            before=before,
            repaired=repaired_info,
            verify_result=verify_result,
            expected_duration_ms=expected_duration_ms,
            source_has_audio=source_has_audio,
            stream_count_overrides=set(),
        )
        all_messages = list(validation_messages)
        if not guard.ok:
            all_messages.extend(message for message in guard.messages if message not in all_messages)
        if not ok or not guard.ok:
            for message in all_messages:
                self._runtime.log(f"❌ Timestamp-Reparatur verworfen: {message}", "error")
            verify_result.messages = list(verify_result.messages or []) + [
                message for message in all_messages if message not in (verify_result.messages or [])
            ]
            # Ein verworfener Kandidat darf unter keinen Umständen später wieder
            # als gültige Ausgabe erscheinen, selbst wenn einzelne ffprobe-Felder OK waren.
            verify_result.duration_ok = False
            duration_s = repaired_info.container_duration_s or verify_result.duration_s
            self._runtime.safe_unlink(tmp)
            return TimestampRepairResult(
                attempted=True,
                verify_result=verify_result,
                duration_s=duration_s,
                reason="Timestamp-Reparatur wurde nach Validierung verworfen.",
                command=command,
                timing_summary=timing_summary,
                retry_recommended=True,
                tool_returncode=run.returncode,
                method=method,
            )

        self._runtime.replace_file(tmp, out)
        duration_s = repaired_info.container_duration_s or verify_result.duration_s
        suffix = " trotz Tool-Returncode" if run.returncode != 0 else ""
        self._runtime.log(f"✅ Timestamp-Reparatur erfolgreich{suffix}: {method}.", "info")
        return TimestampRepairResult(
            attempted=True,
            repaired=True,
            verify_result=verify_result,
            duration_s=duration_s,
            reason=f"Timestamp-Reparatur erfolgreich ({method}).",
            command=command,
            timing_summary=timing_summary,
            retry_recommended=False,
            tool_returncode=run.returncode,
            method=method,
        )

    @staticmethod
    def _candidate_plausible(out: Path, tmp: Path) -> bool:
        try:
            return tmp.exists() and tmp.stat().st_size >= max(1024, int(out.stat().st_size * 0.25))
        except OSError:
            return False

    @staticmethod
    def _is_tolerated_genpts_returncode(returncode: int) -> bool:
        # AVERROR(EINVAL) erscheint je nach Plattform als -22 oder als
        # vorzeichenloser Windows-Prozesscode 2**32 - 22.
        return int(returncode) in {-22, 4_294_967_274}

    def _verify_candidate(self, path: Path, **kwargs):
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
        return self._runtime.output_verifier.verify(str(path), kwargs["container"], **verify_kwargs)
