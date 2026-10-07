# -*- coding: utf-8 -*-
"""Run-scoped support services for :mod:`dv_processing_pipeline`.

This module keeps diagnostics, preflight decisions and temporary execution
lifecycle outside the public pipeline facade.  The facade remains compatible
with existing GUI/workflow consumers while no longer owning these concerns.
"""
from __future__ import annotations

import tempfile
import traceback
import shutil
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

from ..core.models import TargetCodec
from ..core.strict_numbers import nonnegative_integer
from ..core.media_metadata import normalize_video_codec
from ..core.process_runner import subprocess_no_window_kwargs as _no_window_kwargs
from .dv_command_runner import DVCommandRunner
from .dv_failure_recovery import preserve_completed_dv_work
from .dv_pipeline_context import DVPipelineResult, DVPipelineState, DVRunRequest, DVWorkFiles
from .dv_runtime_models import DVEncoderConfig, DVTempState
from .encoder_args import encoder_10bit_filter_pixel_format

LogFn = Callable[[str, str], None]
VerboseFn = Callable[[str], None]


@dataclass
class DVPipelineDiagnostics:
    sidecar_paths: list[str] = field(default_factory=list)
    hdr10plus_verified: bool = False
    dolby_vision_verified: bool = False
    dv_crop_alignment_verified: bool = False
    final_rpu_checked: bool = False
    final_rpu_present: bool = False
    final_rpu_matches_injected: bool | None = None
    final_rpu_expected_sha256: str = ""
    final_rpu_actual_sha256: str = ""
    final_rpu_level5_offsets: tuple[tuple[int, int, int, int], ...] = ()
    final_rpu_level5_dynamic: bool = False
    final_rpu_message: str = ""
    failure_reason: str = ""
    failure_stage: str = ""
    tool_output: str = ""
    effective_crop: str | None = None
    failure_archive_path: str = ""
    failure_artifact_paths: tuple[str, ...] = ()
    preserve_failed_output: bool = False

    def reset(self, temp_state: DVTempState) -> None:
        temp_state.reset_diagnostics()
        self.sidecar_paths.clear()
        self.hdr10plus_verified = False
        self.dolby_vision_verified = False
        self.dv_crop_alignment_verified = False
        self.final_rpu_checked = False
        self.final_rpu_present = False
        self.final_rpu_matches_injected = None
        self.final_rpu_expected_sha256 = ""
        self.final_rpu_actual_sha256 = ""
        self.final_rpu_level5_offsets = ()
        self.final_rpu_level5_dynamic = False
        self.final_rpu_message = ""
        self.failure_reason = ""
        self.failure_stage = ""
        self.tool_output = ""
        self.effective_crop = None
        self.failure_archive_path = ""
        self.failure_artifact_paths = ()
        self.preserve_failed_output = False

    def fail_preflight(
        self,
        temp_state: DVTempState,
        reason: str,
        *,
        stage: str = "DV-Preflight",
    ) -> bool:
        temp_state.record_failure(reason=reason, stage=stage)
        self.failure_reason = reason
        self.failure_stage = stage
        self.tool_output = ""
        return False

    def apply_result(
        self,
        result: DVPipelineResult,
        state: DVPipelineState,
        temp_state: DVTempState,
    ) -> bool:
        self.effective_crop = state.effective_crop
        self.sidecar_paths[:] = list(result.sidecar_paths)
        self.hdr10plus_verified = bool(result.success and result.verified_hdr10plus)
        self.dolby_vision_verified = bool(result.success and result.verified_dolby_vision)
        self.dv_crop_alignment_verified = bool(result.success and getattr(result, "verified_dv_crop_alignment", False))
        self.final_rpu_checked = bool(getattr(result, "final_rpu_checked", False))
        self.final_rpu_present = bool(getattr(result, "final_rpu_present", False))
        self.final_rpu_matches_injected = getattr(result, "final_rpu_matches_injected", None)
        self.final_rpu_expected_sha256 = str(getattr(result, "final_rpu_expected_sha256", "") or "")
        self.final_rpu_actual_sha256 = str(getattr(result, "final_rpu_actual_sha256", "") or "")
        self.final_rpu_level5_offsets = tuple(getattr(result, "final_rpu_level5_offsets", ()) or ())
        self.final_rpu_level5_dynamic = bool(getattr(result, "final_rpu_level5_dynamic", False))
        self.final_rpu_message = str(getattr(result, "final_rpu_message", "") or "")
        self.failure_archive_path = str(getattr(result, "failure_archive_path", "") or "")
        self.failure_artifact_paths = tuple(getattr(result, "failure_artifact_paths", ()) or ())
        self.preserve_failed_output = bool(getattr(result, "preserve_failed_output", False))
        if not result.success:
            self.failure_reason = result.failure_reason or temp_state.failure_reason
            self.failure_stage = result.failure_stage or temp_state.failure_stage
            self.tool_output = temp_state.stderr
        return bool(result.success)

    def record_unhandled_exception(
        self,
        *,
        input_path: str,
        exc: Exception,
        temp_state: DVTempState,
        log: LogFn,
    ) -> bool:
        tb = traceback.format_exc()
        reason = (
            "Unbehandelte Ausnahme in DVProcessingPipeline.run(): "
            f"{type(exc).__name__}: {exc}"
        )
        temp_state.record_failure(
            reason=reason,
            stage="DVProcessingPipeline.run",
            output=tb,
        )
        self.failure_reason = reason
        self.failure_stage = "DVProcessingPipeline.run"
        self.tool_output = tb
        log(
            "❌ Unbehandelte Ausnahme in DVProcessingPipeline.run() "
            f"bei {Path(input_path).name}: {type(exc).__name__}: {exc}",
            "error",
        )
        log(tb, "error")
        return False


class DVFileValidator:
    def __init__(self, *, temp_state: DVTempState, log: LogFn, verbose_log: VerboseFn) -> None:
        self._temp_state = temp_state
        self._log = log
        self._verbose_log = verbose_log

    def assert_nonempty(self, path: Path, label: str) -> bool:
        try:
            exists = path.exists()
            size = path.stat().st_size if exists else 0
        except OSError as exc:
            return self._fail(f"{label}: Datei konnte nicht geprüft werden: {path.name} ({exc})", label)
        if not exists:
            return self._fail(f"{label}: Erwartete Datei fehlt: {path.name}", label)
        if size <= 0:
            return self._fail(f"{label}: Datei ist 0 Byte: {path.name}", label)
        self._verbose_log(f"[DV] OK: {path.name} ({size:,} Byte)")
        return True

    def _fail(self, reason: str, stage: str) -> bool:
        self._temp_state.record_failure(
            reason=reason,
            stage=stage,
            tool=self._temp_state.last_tool,
            command=self._temp_state.last_command,
            output=self._temp_state.stderr,
        )
        self._log(f"❌ [DV] {reason}", "error")
        return False


class DVPreflightService:
    def __init__(
        self,
        *,
        tools: Any,
        log: LogFn,
        verbose_log: VerboseFn,
        libplacebo_available: Callable[[], bool],
    ) -> None:
        self._tools = tools
        self._log = log
        self._verbose_log = verbose_log
        self._libplacebo_available = libplacebo_available

    def validate(
        self,
        *,
        encoder_config: DVEncoderConfig,
        request: DVRunRequest,
    ) -> tuple[bool, str, str]:
        if encoder_config.codec != TargetCodec.H265:
            reason = (
                f"Zielcodec '{encoder_config.codec}' ist nicht kompatibel; "
                "Dolby Vision wird nur für HEVC/H.265 unterstützt"
            )
            self._log(f"❌ DV: {reason}.", "error")
            return False, reason, "DV-Preflight"

        if request.container not in {"mp4", "mkv"}:
            reason = (
                f"Ausgabecontainer '{request.container or '<leer>'}' ist für den DV-Encodepfad ungültig; "
                "erlaubt sind nur MP4 oder MKV"
            )
            self._log(f"❌ DV: {reason}.", "error")
            return False, reason, "DV-Preflight"

        expected_suffix = f".{request.container}"
        actual_suffix = Path(request.output_path).suffix.casefold()
        if actual_suffix != expected_suffix:
            reason = (
                "Ausgabecontainer und Dateiendung widersprechen sich: "
                f"container={request.container}, output={Path(request.output_path).name}. "
                f"Erwartet wird '{expected_suffix}'"
            )
            self._log(f"❌ DV: {reason}.", "error")
            return False, reason, "DV-Preflight"

        if request.profile_major not in {5, 7, 8}:
            reason = (
                "Dolby-Vision-Profil ist für den HEVC-DV-Encodepfad nicht unterstützt: "
                f"Profil {request.profile_major if request.profile_major is not None else 'unbekannt'}. "
                "Unterstützt werden Profile 5, 7 und 8; AV1/DV Profil 10 gehört in den AV1-DV-Pfad"
            )
            self._log(f"❌ DV: {reason}.", "error")
            return False, reason, "DV-Preflight"

        media_info = request.media_info
        if getattr(media_info, "ffmpeg_stream_indices_trusted", True) is False:
            reason = (
                "FFmpeg-Streamindizes der Quellenanalyse sind nicht verlässlich; "
                "DV darf ohne eindeutige Videospurzuordnung nicht gestartet werden"
            )
            self._log(f"❌ DV: {reason}.", "error")
            return False, reason, "DV-Preflight"

        primary_video = getattr(media_info, "primary_video", None)
        if hasattr(media_info, "video_streams") and primary_video is None:
            reason = "DV-Quellenanalyse enthält keine eindeutig primäre Videospur"
            self._log(f"❌ DV: {reason}.", "error")
            return False, reason, "DV-Preflight"
        if primary_video is not None:
            source_codec = normalize_video_codec(getattr(primary_video, "codec", ""))
            if source_codec != "hevc":
                reason = (
                    "DV-Quellprofil und Videocodec sind inkonsistent: "
                    f"Profil {request.profile_major} wurde auf Codec '{source_codec or 'unbekannt'}' erkannt. "
                    "Der HEVC-DV-Pfad akzeptiert nur HEVC-Quellvideo"
                )
                self._log(f"❌ DV: {reason}.", "error")
                return False, reason, "DV-Preflight"
            try:
                source_index = nonnegative_integer(getattr(primary_video, "index"))
            except (TypeError, ValueError, AttributeError):
                source_index = -1
            if source_index < 0:
                reason = (
                    "Primäre DV-Videospur besitzt keinen verlässlichen FFmpeg-Streamindex; "
                    "Track-Auswahl wird nicht geraten"
                )
                self._log(f"❌ DV: {reason}.", "error")
                return False, reason, "DV-Preflight"

        if not request.is_p5:
            return True, "", ""

        self._log(
            "ℹ️  [DV] DV Profile 5 erkannt – libplacebo-HDR10-Encoding wird gestartet.",
            "info",
        )
        if not self._libplacebo_available():
            reason = (
                "DV Profile 5 erfordert ffmpeg mit libplacebo; "
                f"im konfigurierten Binary fehlt libplacebo ({self._tools.ffmpeg})"
            )
            self._log(
                "❌ [DV P5] Das konfigurierte ffmpeg-Binary hat kein libplacebo.\n"
                "   DV Profile 5 erfordert ffmpeg mit --enable-libplacebo.\n"
                "   Lösung: Full-Build verwenden, z.B.:\n"
                "     • gyan.dev  → 'ffmpeg-release-full' oder 'git-full_build'\n"
                "     • BtbN      → 'ffmpeg-master-latest-win64-gpl-shared'\n"
                f"   Aktuell konfiguriert: {self._tools.ffmpeg}",
                "error",
            )
            return False, reason, "DV Profile 5 Preflight"

        self._verbose_log("[DV] DV5-Remux-Fallback wird NICHT verwendet.")
        pixel_format = encoder_10bit_filter_pixel_format(encoder_config.options)
        self._verbose_log(
            "[DV] libplacebo konvertiert ICtCp-Base-Layer direkt zu "
            f"HDR10 (BT.2020nc / PQ / {pixel_format} / TV-Range)."
        )
        self._verbose_log("[DV] RPU wird nach dem Encoding wie bei DV8 re-injiziert.")
        return True, "", ""


class DVPipelineRunExecutor:
    def __init__(
        self,
        *,
        temp_state: DVTempState,
        worker: Any,
        log: LogFn,
        verbose_log: VerboseFn,
        stages_factory: Callable[[], Any],
    ) -> None:
        self._temp_state = temp_state
        self._worker = worker
        self._log = log
        self._verbose_log = verbose_log
        self._stages_factory = stages_factory

    def execute(self, request: DVRunRequest) -> tuple[DVPipelineResult, DVPipelineState]:
        temp_parent = Path(request.output_path).parent
        temp_parent.mkdir(parents=True, exist_ok=True)
        tmp_path = Path(tempfile.mkdtemp(prefix="dragontools_dv_", dir=temp_parent))
        preserve_temp = False
        try:
            state = DVPipelineState(request=request, files=DVWorkFiles.create(tmp_path))
            runner = DVCommandRunner(
                log=self._log,
                verbose_log=self._verbose_log,
                no_window_kwargs=_no_window_kwargs,
                temp_state=self._temp_state,
                worker=self._worker,
            )
            try:
                result = self._stages_factory().run(state, runner)
            except Exception as exc:
                self._verbose_log(traceback.format_exc())
                self._temp_state.record_failure(reason=str(exc), stage="DV-Pipeline-Ausnahme")
                result = DVPipelineResult(False, failure_reason=str(exc), failure_stage="DV-Pipeline-Ausnahme")
            # Protect the workspace even if recovery itself raises unexpectedly.
            preserve_temp = bool(state.video_encode_completed and not result.success)
            result = preserve_completed_dv_work(state, result, log=self._log)
            preserve_temp = bool(getattr(result, "preserve_failed_output", False))
            if preserve_temp and tmp_path.exists():
                artifacts = tuple(dict.fromkeys((
                    *(getattr(result, "failure_artifact_paths", ()) or ()),
                    str(tmp_path),
                )))
                result = replace(result, failure_artifact_paths=artifacts)
                self._log(
                    f"⚠️ [DV] Temporärer Diagnosebestand bleibt wegen unvollständiger "
                    f"Archivierung erhalten: {tmp_path}",
                    "warn",
                )
            return result, state
        finally:
            if not preserve_temp:
                try:
                    shutil.rmtree(tmp_path)
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    self._log(f"⚠️ DV-Tempordner konnte nicht vollständig gelöscht werden: {tmp_path} – {exc}", "warn")


__all__ = [
    "DVFileValidator",
    "DVPipelineDiagnostics",
    "DVPipelineRunExecutor",
    "DVPreflightService",
]
