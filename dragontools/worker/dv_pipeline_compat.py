# -*- coding: utf-8 -*-
"""Legacy diagnostic attribute facade for ``DVProcessingPipeline``."""
from __future__ import annotations


class DVPipelineDiagnosticCompatibilityMixin:
    """Expose historical ``last_*`` attributes over run-scoped diagnostics."""

    @property
    def last_sidecar_paths(self) -> list[str]:
        return self._diagnostics.sidecar_paths

    @last_sidecar_paths.setter
    def last_sidecar_paths(self, value) -> None:
        self._diagnostics.sidecar_paths[:] = list(value or ())

    @property
    def last_hdr10plus_verified(self) -> bool:
        return self._diagnostics.hdr10plus_verified

    @last_hdr10plus_verified.setter
    def last_hdr10plus_verified(self, value) -> None:
        self._diagnostics.hdr10plus_verified = bool(value)

    @property
    def last_dolby_vision_verified(self) -> bool:
        return self._diagnostics.dolby_vision_verified

    @last_dolby_vision_verified.setter
    def last_dolby_vision_verified(self, value) -> None:
        self._diagnostics.dolby_vision_verified = bool(value)

    @property
    def last_failure_reason(self) -> str:
        return self._diagnostics.failure_reason

    @last_failure_reason.setter
    def last_failure_reason(self, value) -> None:
        self._diagnostics.failure_reason = str(value or "")

    @property
    def last_failure_stage(self) -> str:
        return self._diagnostics.failure_stage

    @last_failure_stage.setter
    def last_failure_stage(self, value) -> None:
        self._diagnostics.failure_stage = str(value or "")

    @property
    def last_tool_output(self) -> str:
        return self._diagnostics.tool_output

    @last_tool_output.setter
    def last_tool_output(self, value) -> None:
        self._diagnostics.tool_output = str(value or "")

    @property
    def last_effective_crop(self) -> str | None:
        return self._diagnostics.effective_crop

    @last_effective_crop.setter
    def last_effective_crop(self, value) -> None:
        self._diagnostics.effective_crop = value


__all__ = ["DVPipelineDiagnosticCompatibilityMixin"]
