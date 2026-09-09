# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class WorkerProtocol(Protocol):
    abort_requested: bool
    abort_type: str | None

    def request_abort(self, mode: str = "sofort") -> None:
        ...

    def cancel(self) -> None:
        ...


@runtime_checkable
class PausableWorkerProtocol(WorkerProtocol, Protocol):
    _paused: bool

    def pause(self) -> None:
        ...

    def resume(self) -> None:
        ...


class AnalysisService(Protocol):
    def analyze(self, input_path: str) -> tuple[Any, int | None, int]:
        ...


class PipelineService(Protocol):
    def select_pipeline_context(self, input_path: str, media_info: Any) -> tuple[str, str]:
        ...


class EncodeService(Protocol):
    def prepare_encode_plan(
        self,
        input_path: str,
        output_path: str,
        media_info: Any,
        pipeline: str,
        container: str,
        override: dict,
        *,
        encoder_options: dict | None = None,
        scale_mode: str | None = None,
        codec: str | None = None,
    ) -> Any:
        ...


class VerifyService(Protocol):
    def verify(
        self,
        output_path: str | None,
        container: str,
        *,
        expected_duration_ms: int | None = None,
        source_has_audio: bool = False,
        expected_contract: Any = None,
        verified_hdr10plus: bool = False,
    ) -> Any:
        ...


class ReplaceService(Protocol):
    def replace(self, *, input_path: str, output_path: str | None, container: str) -> str:
        ...


class CleanupService(Protocol):
    def cleanup_temp_artifacts(
        self,
        *,
        burn_sub_tmp: str | None,
        base_dir: Path | None,
        output_path: str | None,
        sidecar_paths: list[str] | None = None,
        keep_output: bool = False,
    ) -> None:
        ...


class ResultService(Protocol):
    def finalize_success(self, ctx: Any) -> None:
        ...

    def finalize_success_pending_postprocess(self, ctx: Any) -> None:
        ...

    def finalize_blocked(self, ctx: Any) -> None:
        ...

    def fail(self, ctx: Any, reason: str) -> None:
        ...


class OutputPathService(Protocol):
    def resolve_output_path(self, input_path: str, container: str) -> tuple[Path, str]:
        ...

    def temp_overwrite_dir(self, base_dir: Path) -> Path:
        ...
