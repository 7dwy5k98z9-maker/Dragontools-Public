# -*- coding: utf-8 -*-
"""Run-scoped support services for :mod:`dv_processing_pipeline`.

This module keeps diagnostics, preflight decisions and temporary execution
lifecycle outside the public pipeline facade.  The facade remains compatible
with existing GUI/workflow consumers while no longer owning these concerns.
"""
from __future__ import annotations

import tempfile
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..core.models import TargetCodec
from ..core.process_runner import subprocess_no_window_kwargs as _no_window_kwargs
from .dv_command_runner import DVCommandRunner
from .dv_pipeline_context import DVPipelineResult, DVPipelineState, DVRunRequest, DVWorkFiles
from .dv_runtime_models import DVEncoderConfig, DVTempState

LogFn = Callable[[str, str], None]
VerboseFn = Callable[[str], None]


@dataclass
class DVPipelineDiagnostics:
    sidecar_paths: list[str] = field(default_factory=list)
    hdr10plus_verified: bool = False
    dolby_vision_verified: bool = False
    failure_reason: str = ""
    failure_stage: str = ""
    tool_output: str = ""
    effective_crop: str | None = None

    def reset(self, temp_state: DVTempState) -> None:
        temp_state.reset_diagnostics()
        self.sidecar_paths.clear()
        self.hdr10plus_verified = False
        self.dolby_vision_verified = False
        self.failure_reason = ""
        self.failure_stage = ""
        self.tool_output = ""
        self.effective_crop = None

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
        self._verbose_log(
            "[DV] libplacebo konvertiert ICtCp-Base-Layer direkt zu "
            "HDR10 (BT.2020nc / PQ / p010le / TV-Range)."
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
        with tempfile.TemporaryDirectory(prefix="dragontools_dv_", dir=temp_parent) as tmp:
            state = DVPipelineState(request=request, files=DVWorkFiles.create(Path(tmp)))
            runner = DVCommandRunner(
                log=self._log,
                verbose_log=self._verbose_log,
                no_window_kwargs=_no_window_kwargs,
                temp_state=self._temp_state,
                worker=self._worker,
            )
            result = self._stages_factory().run(state, runner)
            return result, state


__all__ = [
    "DVFileValidator",
    "DVPipelineDiagnostics",
    "DVPipelineRunExecutor",
    "DVPreflightService",
]
