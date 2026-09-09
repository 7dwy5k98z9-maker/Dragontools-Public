# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DVEncoderConfig:
    codec: str
    crf: int | str
    preset: str
    options: dict = field(default_factory=dict)


@dataclass
class DVTempState:
    burn_sub_tmp: str | None = None
    stderr: str = ""
    failure_reason: str = ""
    failure_stage: str = ""
    last_tool: str = ""
    last_command: str = ""

    def reset_diagnostics(self) -> None:
        """Setzt nur laufbezogene Fehlerdiagnosen zurück, nicht Temp-Dateien."""
        self.stderr = ""
        self.failure_reason = ""
        self.failure_stage = ""
        self.last_tool = ""
        self.last_command = ""

    def record_failure(
        self,
        *,
        reason: str,
        stage: str = "",
        tool: str = "",
        command: str = "",
        output: str = "",
    ) -> None:
        self.failure_reason = str(reason or "").strip()
        self.failure_stage = str(stage or "").strip()
        self.last_tool = str(tool or "").strip()
        self.last_command = str(command or "").strip()
        self.stderr = str(output or "").strip()
