# -*- coding: utf-8 -*-
from __future__ import annotations

import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Callable

from ..core.process_runner import tool_available
from .duration_remux_service import DurationRemuxService
from .duration_repair_commands import (
    _command_arg_after,
    _setts_filter_for_fps,
)
from .duration_repair_models import (
    DurationRepairOutcome,
    MediaTimingInfo,
    TimestampRepairResult,
    calculate_expected_duration,
    detect_timestamp_problem,
    duration_close as _duration_close,
)
from .duration_repair_runtime import DurationRepairRuntime
from .duration_repair_validation import validate_timestamp_repair as _validate_timestamp_repair
from .duration_timing_analyzer import MediaTimingAnalyzer
from .duration_timestamp_service import TimestampRepairService
from .tool_runner import ToolRunResult, run_tool
from .workflow_engine import WorkflowVerifyResult


def _fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "unbekannt"
    try:
        return f"{float(seconds):.1f}s"
    except (TypeError, ValueError):
        return "unbekannt"


def _unique_archive_path(archive_dir: Path, filename: str) -> Path:
    candidate = archive_dir / filename
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    counter = 1
    while True:
        numbered = archive_dir / f"{stem}_{counter}{suffix}"
        if not numbered.exists():
            return numbered
        counter += 1


class DurationRepairService:
    """Coordinates lossless duration repair without owning stage internals.

    Public and historically test-used private methods stay available as thin
    compatibility wrappers while the actual remux/timestamp responsibilities
    live in dedicated services.
    """

    def __init__(
        self,
        *,
        mkvmerge_path: str,
        output_verifier,
        mp4box_path: str = "",
        log: Callable[[str, str], None],
        ffmpeg_path: str = "",
        ffprobe_path: str = "",
        mediainfo_path: str = "",
        normal_remux_enabled: bool = True,
        timestamp_repair_enabled: bool = True,
        worker=None,
        run_tool_fn: Callable[..., ToolRunResult] | None = None,
    ) -> None:
        resolved_ffprobe = str(ffprobe_path or getattr(output_verifier, "_ffprobe_path", "") or "")
        self._normal_remux_enabled = bool(normal_remux_enabled)
        self._timestamp_repair_enabled = bool(timestamp_repair_enabled)
        self._runtime = DurationRepairRuntime(
            mkvmerge_path=str(mkvmerge_path or ""),
            mp4box_path=str(mp4box_path or ""),
            ffmpeg_path=str(ffmpeg_path or ""),
            ffprobe_path=resolved_ffprobe,
            mediainfo_path=str(mediainfo_path or ""),
            output_verifier=output_verifier,
            log=log,
            worker=worker,
            run_tool_fn=run_tool_fn or run_tool,
        )
        self._timing_analyzer = MediaTimingAnalyzer(
            ffprobe_path=self._runtime.ffprobe_path,
            mediainfo_path=self._runtime.mediainfo_path,
            run_command=subprocess.run,
        )
        self._remux_service = DurationRemuxService(self._runtime)
        self._timestamp_service = TimestampRepairService(self._runtime, self._timing_analyzer)

        # Compatibility attributes used by older internal code/tests. They are
        # aliases only; no duplicated state or business logic lives here.
        self._mkvmerge_path = self._runtime.mkvmerge_path
        self._mp4box_path = self._runtime.mp4box_path
        self._output_verifier = self._runtime.output_verifier
        self._log = self._runtime.log
        self._ffmpeg_path = self._runtime.ffmpeg_path
        self._ffprobe_path = self._runtime.ffprobe_path
        self._mediainfo_path = self._runtime.mediainfo_path
        self._worker = self._runtime.worker
        self._run_tool = self._runtime.run_tool_fn

    def can_repair(
        self,
        *,
        output_path: str | None,
        container: str,
        verify_result: WorkflowVerifyResult,
    ) -> bool:
        if not output_path:
            return False
        if not (self._normal_remux_enabled or self._timestamp_repair_enabled):
            return False
        container_name = str(container or "").strip().lower().lstrip(".")
        suffix = Path(output_path).suffix.lower()
        if not (
            (container_name == "mkv" and suffix == ".mkv")
            or (container_name == "mp4" and suffix == ".mp4")
        ):
            return False
        return (
            bool(verify_result.exists)
            and bool(verify_result.size_ok)
            and bool(verify_result.container_ok)
            and bool(verify_result.probe_ok)
            and bool(verify_result.video_ok)
            and bool(verify_result.audio_ok)
            and bool(getattr(verify_result, "subtitle_ok", True))
            and bool(getattr(verify_result, "contract_ok", True))
            and bool(getattr(verify_result, "metadata_ok", True))
            and not bool(verify_result.duration_ok)
        )

    def repair(
        self,
        *,
        output_path: str | None,
        base_dir: Path | None,
        container: str,
        expected_duration_ms: int | None,
        source_has_audio: bool,
        initial_result: WorkflowVerifyResult,
        expected_contract=None,
        verified_hdr10plus: bool = False,
        verified_dolby_vision: bool = False,
    ) -> DurationRepairOutcome:
        if not self.can_repair(
            output_path=output_path,
            container=container,
            verify_result=initial_result,
        ):
            return DurationRepairOutcome(verify_result=initial_result)

        out = Path(str(output_path))
        expected_s = expected_duration_ms / 1000.0 if expected_duration_ms else None
        ffmpeg_s = initial_result.duration_s
        self._log(
            f"⚠️ Ausgabedauer unplausibel - automatische {str(container).upper()}-Reparatur startet.",
            "warn",
        )
        self._log(
            f"   Quelle: {_fmt_duration(expected_s)} | nach FFmpeg: {_fmt_duration(ffmpeg_s)}",
            "warn",
        )

        remux_result = initial_result
        remux_s: float | None = None
        remux_message = ""

        remux_tool_path, remux_tool_label = self._normal_remux_tool(container)
        if not self._normal_remux_enabled:
            remux_message = "Normaler Container-Remux ist in den Einstellungen deaktiviert."
            self._log(f"ℹ️ {remux_message}", "info")
        elif remux_tool_path and tool_available(remux_tool_path):
            remux_result, remux_s, remux_ok, remux_message = self.attempt_normal_remux(
                out=out,
                container=container,
                expected_duration_ms=expected_duration_ms,
                source_has_audio=source_has_audio,
                initial_result=initial_result,
                expected_contract=expected_contract,
                verified_hdr10plus=verified_hdr10plus,
                verified_dolby_vision=verified_dolby_vision,
            )
            if remux_ok:
                return DurationRepairOutcome(
                    attempted=True,
                    repaired=True,
                    verify_result=remux_result,
                    remux_duration_s=remux_s,
                    message="Laufzeit durch automatischen Remux korrigiert.",
                )
        else:
            remux_message = f"{remux_tool_label} wurde nicht gefunden - normaler Remux wird übersprungen."
            self._log(f"⚠️ {remux_message}", "warn")

        if self._timestamp_repair_enabled:
            timestamp_result = self._try_timestamp_repair(
                out=out,
                container=container,
                expected_duration_ms=expected_duration_ms,
                expected_duration_s=expected_s,
                source_has_audio=source_has_audio,
                reference_result=remux_result,
                expected_contract=expected_contract,
                verified_hdr10plus=verified_hdr10plus,
                verified_dolby_vision=verified_dolby_vision,
            )
        else:
            reason = "Timestamp-Reparatur ist in den Einstellungen deaktiviert."
            self._log(f"ℹ️ {reason}", "info")
            timestamp_result = TimestampRepairResult(verify_result=remux_result, reason=reason)

        if timestamp_result.repaired:
            return DurationRepairOutcome(
                attempted=True,
                repaired=True,
                verify_result=timestamp_result.verify_result,
                remux_duration_s=remux_s,
                timestamp_fix_attempted=timestamp_result.attempted,
                timestamp_fixed=True,
                timestamp_duration_s=timestamp_result.duration_s,
                timestamp_repair_reason=timestamp_result.reason,
                timestamp_repair_cmd=timestamp_result.command,
                timestamp_ffmpeg_cmd=timestamp_result.command,
                timing_summary=timestamp_result.timing_summary,
                message="Laufzeit durch automatische Timestamp-Reparatur korrigiert.",
            )

        final_result = timestamp_result.verify_result or remux_result or initial_result
        messages = list(getattr(final_result, "messages", []) or [])
        if remux_message and remux_message not in messages:
            messages.append(remux_message)
        if timestamp_result.reason and timestamp_result.reason not in messages:
            messages.append(timestamp_result.reason)
        if remux_s is not None:
            messages.append("Laufzeit blieb auch nach automatischem Container-Remux unplausibel.")

        self._log("❌ Laufzeit bleibt nach automatischer Reparatur unplausibel.", "error")
        self._log(
            f"   Quelle: {_fmt_duration(expected_s)} | nach FFmpeg: {_fmt_duration(ffmpeg_s)} | "
            f"nach Remux: {_fmt_duration(remux_s)} | nach Timestamp-Fix: "
            f"{_fmt_duration(timestamp_result.duration_s)}",
            "error",
        )
        archived = self._archive_output(out, base_dir)
        if archived:
            messages.append(f"Fehlerhafte Ausgabedatei wurde archiviert: {archived}")

        self._mark_failed_result(final_result, messages)
        return DurationRepairOutcome(
            attempted=True,
            repaired=False,
            verify_result=final_result,
            archived_path=archived,
            remux_duration_s=remux_s,
            timestamp_fix_attempted=timestamp_result.attempted,
            timestamp_fixed=False,
            timestamp_duration_s=timestamp_result.duration_s,
            timestamp_repair_reason=timestamp_result.reason,
            timestamp_repair_cmd=timestamp_result.command,
            timestamp_ffmpeg_cmd=timestamp_result.command,
            timing_summary=timestamp_result.timing_summary,
            keep_failed_output=True,
            message="Laufzeit blieb auch nach automatischer Reparatur unplausibel.",
        )

    @staticmethod
    def _mark_failed_result(final_result, messages: list[str]) -> None:
        """Haelt einen verworfenen Reparaturpfad fuer alle Aufrufer fail-closed."""
        final_result.duration_ok = False
        reject_message = (
            "Automatische Reparatur endgueltig verworfen; die Datei darf nicht "
            "als fertige Ausgabe uebernommen werden."
        )
        if reject_message not in messages:
            messages.append(reject_message)
        final_result.messages = messages

    # --- Compatibility surface -------------------------------------------------
    # Existing tests/internal callers historically reached these methods on the
    # coordinator. Keep forwarding wrappers during the staged refactoring.

    def attempt_normal_remux(self, **kwargs):
        return self._remux_service.attempt(**kwargs)

    def _normal_remux_tool(self, container: str) -> tuple[str, str]:
        return self._remux_service.normal_remux_tool(container)

    def _try_timestamp_repair(self, **kwargs) -> TimestampRepairResult:
        return self._timestamp_service.try_repair(**kwargs)

    def get_media_timing_info(self, path: str, *, expected_duration_s: float | None = None) -> MediaTimingInfo:
        return self._timestamp_service.get_media_timing_info(path, expected_duration_s=expected_duration_s)

    def repair_video_timestamps(self, **kwargs) -> TimestampRepairResult:
        return self._timestamp_service.repair_video_timestamps(**kwargs)

    def validate_timestamp_repair(
        self,
        *,
        before: MediaTimingInfo,
        repaired: MediaTimingInfo,
        verify_result: WorkflowVerifyResult,
        expected_duration_ms: int | None,
        source_has_audio: bool,
    ) -> tuple[bool, list[str]]:
        return _validate_timestamp_repair(
            before=before,
            repaired=repaired,
            verify_result=verify_result,
            expected_duration_ms=expected_duration_ms,
            source_has_audio=source_has_audio,
        )

    def _build_timestamp_repair_command(
        self,
        source: Path,
        target: Path,
        fps: Fraction,
        *,
        container: str | None = None,
    ) -> list[str]:
        return self._timestamp_service.build_timestamp_repair_command(
            source,
            target,
            fps,
            container=container,
        )

    def _run_ffprobe_json(self, path: str, *, count_frames: bool = False) -> dict:
        return self._timing_analyzer.run_ffprobe_json(path, count_frames=count_frames)

    def _run_mediainfo_json(self, path: str) -> dict:
        return self._timing_analyzer.run_mediainfo_json(path)

    def _apply_ffprobe_timing(self, info: MediaTimingInfo, data: dict) -> None:
        self._timing_analyzer.apply_ffprobe_timing(info, data)

    def _apply_mediainfo_timing(self, info: MediaTimingInfo, data: dict) -> None:
        self._timing_analyzer.apply_mediainfo_timing(info, data)

    def _derive_frame_rate_from_source_duration(
        self,
        info: MediaTimingInfo,
        expected_duration_s: float | None,
    ) -> None:
        self._timing_analyzer.derive_frame_rate_from_source_duration(info, expected_duration_s)

    def _infer_frame_rate_mode(self, info: MediaTimingInfo) -> str:
        return self._timing_analyzer.infer_frame_rate_mode(info)

    def _timing_summary(self, info: MediaTimingInfo) -> list[str]:
        return self._timestamp_service.timing_summary(info)

    def _ffmpeg_supports_setts(self) -> bool:
        return self._timestamp_service.ffmpeg_supports_setts()

    def _archive_output(self, output_path: Path, base_dir: Path | None) -> str | None:
        if not output_path.exists():
            return None
        root = Path(base_dir) if base_dir is not None else output_path.parent
        archive_dir = root / "Archiv"
        try:
            archive_dir.mkdir(parents=True, exist_ok=True)
            target = _unique_archive_path(archive_dir, output_path.name)
            self._runtime.replace_file(output_path, target)
            self._log(
                "📦 Datei aufgrund weiterhin fehlerhafter Laufzeit in den Archiv-Ordner verschoben: "
                f"{target}",
                "warn",
            )
            return str(target)
        except Exception as exc:
            self._log(f"❌ Archivierung der fehlerhaften Ausgabedatei fehlgeschlagen: {exc}", "error")
            return None

    def _safe_unlink(self, path: Path) -> None:
        self._runtime.safe_unlink(path)
