# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from .duration_repair_models import MediaTimingInfo, TimestampRepairResult
from .duration_repair_stream_guard import RepairStreamGuard, StreamInventory
from .duration_timestamp_candidate_archive import RejectedTimestampArchive
from .duration_timestamp_candidate_validation import TimestampCandidateValidator


class TimestampCandidateService:
    """Executes one timestamp repair candidate and commits it only after full validation."""

    def __init__(self, runtime, timing_analyzer, stream_guard: RepairStreamGuard) -> None:
        self._runtime = runtime
        self._timing_analyzer = timing_analyzer
        self._stream_guard = stream_guard
        self._archive = RejectedTimestampArchive(runtime)
        self._validator = TimestampCandidateValidator(runtime, timing_analyzer, stream_guard)

    def attempt(self, *, out: Path, tmp: Path, base_dir: Path | None = None, command: list[str], label: str,
                method: str, container: str, before: MediaTimingInfo, before_ffprobe: StreamInventory,
                before_mediainfo: StreamInventory, before_mkvmerge: StreamInventory | None = None,
                expected_duration_ms: int | None = None, source_has_audio: bool = False,
                timing_summary: list[str], expected_contract=None, verified_hdr10plus: bool = False,
                verified_dolby_vision: bool = False, source_reference: MediaTimingInfo | None = None) -> TimestampRepairResult:
        run = self._runtime.run_tool(command, label=label)
        candidate_exists = self._candidate_plausible(out, tmp)
        failure = self._handle_tool_result(
            run, out=out, tmp=tmp, base_dir=base_dir, label=label, method=method,
            command=command, timing_summary=timing_summary, candidate_exists=candidate_exists,
        )
        if failure is not None:
            return failure
        if not candidate_exists:
            return self._reject_missing_candidate(run, out, tmp, base_dir, label, method, command, timing_summary)

        validation = self._validator.validate(
            tmp,
            container=container,
            before=before,
            before_ffprobe=before_ffprobe,
            before_mediainfo=before_mediainfo,
            before_mkvmerge=before_mkvmerge,
            expected_duration_ms=expected_duration_ms,
            source_has_audio=source_has_audio,
            expected_contract=expected_contract,
            verified_hdr10plus=verified_hdr10plus,
            verified_dolby_vision=verified_dolby_vision,
            source_reference=source_reference,
        )
        if not validation.ok:
            return self._reject_invalid_candidate(
                validation, run, out, tmp, base_dir, label, method, command, timing_summary
            )
        self._runtime.replace_file(tmp, out)
        duration_s = validation.repaired_info.container_duration_s or validation.verify_result.duration_s
        suffix = " trotz Tool-Returncode" if run.returncode != 0 else ""
        self._runtime.log(f"✅ Timestamp-Reparatur erfolgreich{suffix}: {method}.", "info")
        return TimestampRepairResult(
            attempted=True, repaired=True, verify_result=validation.verify_result, duration_s=duration_s,
            reason=f"Timestamp-Reparatur erfolgreich ({method}).", command=command, timing_summary=timing_summary,
            retry_recommended=False, tool_returncode=run.returncode, method=method,
        )

    def _handle_tool_result(self, run, *, out, tmp, base_dir, label, method, command, timing_summary, candidate_exists):
        if run.returncode == 0:
            return None
        detail_lines = (run.stderr or run.stdout or "").strip().splitlines()
        detail = detail_lines[-1] if detail_lines else f"Returncode {run.returncode}"
        tolerated = (
            (method.startswith("FFmpeg +genpts") and self._is_tolerated_genpts_returncode(run.returncode))
            or (method.startswith("MKVToolNix") and int(run.returncode) == 1)
        )
        if not candidate_exists or not tolerated:
            self._runtime.log(f"❌ {label} fehlgeschlagen: {detail}", "error")
            self._archive.archive(tmp, out=out, base_dir=base_dir, label=label, reason=f"{label} fehlgeschlagen: {detail}")
            return self._failure_result(f"{label} fehlgeschlagen: {detail}", run, method, command, timing_summary)
        self._runtime.log(
            f"⚠️ {label} endete mit Returncode {run.returncode}, hat aber eine Ausgabedatei erzeugt. "
            "Der Kandidat wird vollständig bis zum Dateiende geprüft.", "warn"
        )
        try:
            self._timing_analyzer.run_ffprobe_json(str(tmp), count_frames=True)
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            self._runtime.log(f"❌ Kandidat mit FFmpeg-EINVAL ist nicht vollständig lesbar: {exc}", "error")
            self._archive.archive(tmp, out=out, base_dir=base_dir, label=label, reason="FFmpeg-EINVAL-Kandidat nicht vollständig lesbar")
            return self._failure_result(
                "FFmpeg-+genpts/+igndts-Kandidat war nach EINVAL nicht vollständig lesbar.", run, method, command, timing_summary
            )
        return None

    def _reject_missing_candidate(self, run, out, tmp, base_dir, label, method, command, timing_summary):
        reason = "Timestamp-Reparatur erzeugte keine plausible Ausgabedatei."
        self._archive.archive(tmp, out=out, base_dir=base_dir, label=label, reason=reason.rstrip("."))
        return self._failure_result(reason, run, method, command, timing_summary)

    def _reject_invalid_candidate(self, validation, run, out, tmp, base_dir, label, method, command, timing_summary):
        for message in validation.messages:
            self._runtime.log(f"❌ Timestamp-Reparatur verworfen: {message}", "error")
        verify = validation.verify_result
        verify.messages = list(verify.messages or []) + [m for m in validation.messages if m not in (verify.messages or [])]
        verify.duration_ok = False
        duration_s = validation.repaired_info.container_duration_s or verify.duration_s
        self._archive.archive(tmp, out=out, base_dir=base_dir, label=label, reason="Timestamp-Reparatur wurde nach Validierung verworfen")
        return TimestampRepairResult(
            attempted=True, verify_result=verify, duration_s=duration_s,
            reason="Timestamp-Reparatur wurde nach Validierung verworfen.", command=command,
            timing_summary=timing_summary, retry_recommended=True, tool_returncode=run.returncode, method=method,
        )

    @staticmethod
    def _failure_result(reason, run, method, command, timing_summary) -> TimestampRepairResult:
        return TimestampRepairResult(
            attempted=True, reason=reason, command=command, timing_summary=timing_summary,
            retry_recommended=True, tool_returncode=run.returncode, method=method,
        )

    def _archive_rejected_candidate(self, tmp: Path, *, out: Path, base_dir: Path | None, label: str, reason: str) -> str | None:
        return self._archive.archive(tmp, out=out, base_dir=base_dir, label=label, reason=reason)

    @staticmethod
    def _archive_root_for(out: Path) -> Path:
        return RejectedTimestampArchive.archive_root_for(out)

    @staticmethod
    def _safe_archive_label(label: str) -> str:
        return RejectedTimestampArchive.safe_label(label)

    @staticmethod
    def _candidate_plausible(out: Path, tmp: Path) -> bool:
        try:
            return tmp.exists() and tmp.stat().st_size >= max(1024, int(out.stat().st_size * 0.25))
        except OSError:
            return False

    @staticmethod
    def _is_tolerated_genpts_returncode(returncode: int) -> bool:
        return int(returncode) in {-22, 4_294_967_274}

    def _verify_candidate(self, path: Path, **kwargs):
        return self._validator.verify_output(path, container=kwargs["container"], **{k: v for k, v in kwargs.items() if k != "container"})
