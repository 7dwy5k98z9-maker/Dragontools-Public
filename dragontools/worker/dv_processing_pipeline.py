# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
import traceback
from pathlib import Path

from ..core.process_runner import subprocess_no_window_kwargs as _no_window_kwargs
from .dv_audio_mux_service import DVAudioMuxService
from .dv_failure_recovery import DVFailureRecovery
from .dv_level5_editor import DVLevel5Editor
from .dv_mp4box_muxer import DVMP4BoxMuxer
from .dv_mkv_muxer import DVMKVMuxer
from .dv_rpu_service import DVRpuService
from .dv_command_runner import DVCommandRunner
from .dv_pipeline_context import DVRunRequest, DVPipelineState, DVWorkFiles
from .dv_pipeline_stages import DVPipelineStages
from .dv_runtime_models import DVEncoderConfig, DVTempState
from .subtitle_sidecar_service import SubtitleSidecarService
from .dv_subtitle_mux_service import DVSubtitleMuxService
from .tool_runner import run_tool
from .hdr10plus_bitstream_service import HDR10PlusBitstreamService
from ..core.models import TargetCodec
class DVProcessingPipeline:
    def __init__(
        self,
        *,
        tools,
        encoder_config: DVEncoderConfig,
        progress_runner,
        subtitle_rules: dict,
        temp_state: DVTempState,
        log,
        verbose_logger=None,
        worker=None,
    ) -> None:
        self._tools = tools
        self._verbose_logger = verbose_logger  # VerboseLogger oder None
        self._encoder_config = encoder_config
        self._progress_runner = progress_runner
        self._subtitle_rules = subtitle_rules
        self._temp_state = temp_state
        self._log_fn = log
        self._worker = worker
        self.last_sidecar_paths: list[str] = []
        self.last_hdr10plus_verified: bool = False
        self.last_dolby_vision_verified: bool = False
        self.last_failure_reason: str = ""
        self.last_failure_stage: str = ""
        self.last_tool_output: str = ""
        self._audio_mux_service = DVAudioMuxService(
            ffmpeg_path=self._tools.ffmpeg,
            ffprobe_path=self._tools.ffprobe,
            mp4box_muxer=None,
            log=self._detail_log,
        )
        self._mp4box_muxer = DVMP4BoxMuxer(
            mp4box_path=self._tools.mp4box,
            audio_track_name=lambda meta: self._audio_mux_service.audio_track_name(meta),
        )
        self._audio_mux_service._mp4box_muxer = self._mp4box_muxer
        self._mkv_muxer = DVMKVMuxer(mkvmerge_path=getattr(self._tools, "mkvmerge", "mkvmerge"), audio_track_name=self._audio_mux_service.audio_track_name)
        self._rpu_service = DVRpuService(
            dovi_tool_path=self._tools.dovi_tool,
            log=self._detail_log,
        )
        self._hdr10plus_service = HDR10PlusBitstreamService(
            hdr10plus_tool_path=self._tools.hdr10plus_tool,
            log=self._detail_log,
        )
        self._level5_editor = DVLevel5Editor(
            dovi_tool_path=self._tools.dovi_tool,
            log=self._detail_log,
        )
        self._subtitle_service = SubtitleSidecarService(
            ffmpeg_path=self._tools.ffmpeg,
            subtitle_rules=self._subtitle_rules,
            log=self._log, worker=self._worker,
        )
        self._subtitle_mux_service = DVSubtitleMuxService(
            ffmpeg_path=self._tools.ffmpeg, subtitle_rules=self._subtitle_rules, log=self._log
        )
        self._failure_recovery = DVFailureRecovery(log=self._log)

    def _log(self, message: str, level: str = "info") -> None:
        self._log_fn(message, level)

    def _vlog(self, message: str) -> None:
        """Verbose-Log: nur in VerboseLog-Datei, nicht in GUI/normales Log."""
        try:
            if self._verbose_logger:
                self._verbose_logger.write(message)
        except Exception:
            pass

    def _detail_log(self, message: str, level: str = "info") -> None:
        """Technische DV-Unterdetails nur bei Warnungen/Fehlern ins Hauptlog."""
        if str(level).lower() in {"warn", "warning", "error"}:
            self._log(message, "warn" if str(level).lower() == "warning" else level)
        else:
            self._vlog(message)

    def _clear_burn_sub_tmp(self) -> None:
        self._temp_state.burn_sub_tmp = None

    def _libplacebo_available(self) -> bool:
        """Prüft den ffmpeg-Filterumfang über den zentralen Tool-Runner."""
        try:
            result = run_tool(
                [self._tools.ffmpeg, "-filters"],
                label="ffmpeg libplacebo probe",
                timeout_s=15,
                worker=self._worker,
            )
        except (OSError, ValueError, RuntimeError):
            return False

        if result.returncode != 0 or result.timed_out or result.aborted:
            return False
        return "libplacebo" in result.combined_output.lower()

    def _assert_nonempty_file(self, path: Path, label: str) -> bool:
        """Validiert eine erwartete Zwischendatei und setzt die DV-Diagnose."""
        try:
            exists = path.exists()
            size = path.stat().st_size if exists else 0
        except OSError as exc:
            reason = f"{label}: Datei konnte nicht geprüft werden: {path.name} ({exc})"
            self._record_file_validation_failure(reason, label)
            self._log(f"❌ [DV] {reason}", "error")
            return False

        if not exists:
            reason = f"{label}: Erwartete Datei fehlt: {path.name}"
            self._record_file_validation_failure(reason, label)
            self._log(f"❌ [DV] {reason}", "error")
            return False
        if size <= 0:
            reason = f"{label}: Datei ist 0 Byte: {path.name}"
            self._record_file_validation_failure(reason, label)
            self._log(f"❌ [DV] {reason}", "error")
            return False

        self._vlog(f"[DV] OK: {path.name} ({size:,} Byte)")
        return True

    def _record_file_validation_failure(self, reason: str, stage: str) -> None:
        self._temp_state.record_failure(
            reason=reason,
            stage=stage,
            tool=self._temp_state.last_tool,
            command=self._temp_state.last_command,
            output=self._temp_state.stderr,
        )

    def _build_stages(self) -> DVPipelineStages:
        """Verdrahtet die fachlichen DV-Stufen mit den Pipeline-Services."""
        return DVPipelineStages(
            tools=self._tools,
            encoder_config=self._encoder_config,
            progress_runner=self._progress_runner,
            temp_state=self._temp_state,
            audio_mux_service=self._audio_mux_service,
            mp4box_muxer=self._mp4box_muxer,
            mkv_muxer=self._mkv_muxer,
            rpu_service=self._rpu_service,
            hdr10plus_service=self._hdr10plus_service,
            level5_editor=self._level5_editor,
            subtitle_service=self._subtitle_service,
            subtitle_mux_service=self._subtitle_mux_service,
            subtitle_rules=self._subtitle_rules,
            failure_recovery=self._failure_recovery,
            log=self._log,
            verbose_log=self._vlog,
            assert_nonempty_file=self._assert_nonempty_file,
            clear_burn_sub_tmp=self._clear_burn_sub_tmp,
            crop_decision=getattr(self._worker, "request_dv_crop_decision", None),
        )

    def _reset_run_diagnostics(self) -> None:
        self._temp_state.reset_diagnostics()
        self.last_sidecar_paths = []  # Run-lokaler Output-State darf nie in den Folgejob leaken.
        self.last_hdr10plus_verified = False
        self.last_dolby_vision_verified = False
        self.last_failure_reason = ""
        self.last_failure_stage = ""
        self.last_tool_output = ""
        self.last_effective_crop = None

    def _store_failed_result(self, result) -> None:
        if result.success:
            return
        self.last_failure_reason = result.failure_reason or self._temp_state.failure_reason
        self.last_failure_stage = result.failure_stage or self._temp_state.failure_stage
        self.last_tool_output = self._temp_state.stderr

    def _fail_preflight(self, reason: str, *, stage: str = "DV-Preflight") -> bool:
        self._temp_state.record_failure(reason=reason, stage=stage)
        self.last_failure_reason = reason
        self.last_failure_stage = stage
        self.last_tool_output = ""
        return False

    def _handle_run_exception(self, input_path: str, exc: Exception) -> bool:
        tb = traceback.format_exc()
        reason = (
            "Unbehandelte Ausnahme in DVProcessingPipeline.run(): "
            f"{type(exc).__name__}: {exc}"
        )
        self._temp_state.record_failure(
            reason=reason,
            stage="DVProcessingPipeline.run",
            output=tb,
        )
        self.last_failure_reason = reason
        self.last_failure_stage = "DVProcessingPipeline.run"
        self.last_tool_output = tb
        self._log(
            f"❌ Unbehandelte Ausnahme in DVProcessingPipeline.run() "
            f"bei {Path(input_path).name}: {type(exc).__name__}: {exc}",
            "error",
        )
        self._log(tb, "error")
        return False
    def configure_encoder(self, encoder_config: DVEncoderConfig) -> None:
        """Setzt die effektive per-Datei-Encoderkonfiguration ueber eine oeffentliche API."""
        self._encoder_config = encoder_config
    def run(
        self,
        input_path: str,
        output_path: str,
        mi,
        vf_args: list,
        audio_args: list,
        audio_input_args: list | None,
        sn: list,
        crop: str | None,
        ov: dict | None = None,
        preserve_hdrplus: bool = False,
        container: str = "mp4",
    ) -> bool:
        """Führt den DV-Workflow als schlanke Orchestrierung aus.

        Die fachlichen Schritte liegen in :class:`DVPipelineStages`. Hier
        verbleiben nur Request-Normalisierung, Profil-Preflight, Temp-Lifecycle
        und die äußere Fehlergrenze.
        """
        try:
            self._reset_run_diagnostics()
            self._vlog("[TRACE][DV] entered dv_processing_pipeline")
            if self._encoder_config.codec != TargetCodec.H265:
                reason = (
                    f"Zielcodec '{self._encoder_config.codec}' ist nicht kompatibel; "
                    "Dolby Vision wird nur für HEVC/H.265 unterstützt"
                )
                self._log(f"❌ DV: {reason}.", "error")
                return self._fail_preflight(reason)

            request = DVRunRequest.create(
                input_path=input_path,
                output_path=output_path,
                media_info=mi,
                vf_args=vf_args,
                audio_args=audio_args,
                audio_input_args=audio_input_args,
                sn=sn,
                crop=crop,
                override=ov,
                preserve_hdrplus=preserve_hdrplus,
                container=container,
            )

            # DV Profile 5 ist kein normaler HDR10-Base-Layer. Es muss aus
            # dem Originalcontainer über libplacebo von ICtCp nach
            # BT.2020nc/PQ konvertiert werden. Kein stiller Remux-Fallback.
            if request.is_p5:
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
                    return self._fail_preflight(reason, stage="DV Profile 5 Preflight")
                self._vlog("[DV] DV5-Remux-Fallback wird NICHT verwendet.")
                self._vlog(
                    "[DV] libplacebo konvertiert ICtCp-Base-Layer direkt zu "
                    "HDR10 (BT.2020nc / PQ / p010le / TV-Range)."
                )
                self._vlog("[DV] RPU wird nach dem Encoding wie bei DV8 re-injiziert.")

            temp_parent = Path(output_path).parent
            temp_parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix="dragontools_dv_",
                dir=temp_parent,
            ) as tmp:
                state = DVPipelineState(
                    request=request,
                    files=DVWorkFiles.create(Path(tmp)),
                )
                runner = DVCommandRunner(
                    log=self._log,
                    verbose_log=self._vlog,
                    no_window_kwargs=_no_window_kwargs,
                    temp_state=self._temp_state,
                    worker=self._worker,
                )
                result = self._build_stages().run(state, runner)
                self.last_effective_crop = state.effective_crop
                self.last_sidecar_paths = list(result.sidecar_paths)
                # Verifizierungsflags stammen ausschließlich aus der finalen Post-Mux-Prüfung.
                self.last_hdr10plus_verified = bool(result.success and result.verified_hdr10plus)
                self.last_dolby_vision_verified = bool(result.success and result.verified_dolby_vision)
                self._store_failed_result(result)
                return result.success

        except Exception as exc:
            return self._handle_run_exception(input_path, exc)
