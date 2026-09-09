# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable

from ..core.timeout_settings import get_timeout
from .command_formatting import command_to_log_string
from .tool_runner import ToolRunResult


class HDRPlusToolRunner:
    """Zentrale Prozessausfuehrung fuer den HDR10+-Workflow.

    Der Runner enthaelt bewusst keine HDR10+-Fachlogik. Er vereinheitlicht nur
    Timeout-Modus, Worker-Abbruch, Returncode-Behandlung und Diagnosedaten im
    ``DVTempState``. Dadurch muessen Metadata- und Mux-Services keine eigenen
    Varianten derselben Tool-Runner-Logik pflegen.
    """

    def __init__(
        self,
        *,
        run_tool_fn: Callable[..., ToolRunResult],
        log_tool_failure_fn: Callable[..., None],
        log: Callable[[str, str], None],
        temp_state,
        worker=None,
    ) -> None:
        self._run_tool_fn = run_tool_fn
        self._log_tool_failure_fn = log_tool_failure_fn
        self._log = log
        self._temp_state = temp_state
        self._worker = worker

    def _remember_command(self, command: list[str], label: str) -> None:
        state = self._temp_state
        state.stderr = ""
        state.failure_reason = ""
        state.failure_stage = ""
        state.last_tool = Path(command[0]).name if command else ""
        state.last_command = command_to_log_string(command) if command else ""

    def _remember_result(self, result: ToolRunResult) -> None:
        self._temp_state.stderr = result.tail(20)

    def capture(
        self,
        cmd: Iterable[object],
        *,
        label: str,
        timeout_s: int | float | None,
        timeout_mode: str = "absolute",
    ) -> ToolRunResult:
        command = [str(part) for part in cmd]
        self._remember_command(command, label)
        result = self._run_tool_fn(
            command,
            label=label,
            timeout_s=timeout_s,
            timeout_mode=timeout_mode,
            worker=self._worker,
            log=self._log,
        )
        self._remember_result(result)
        return result

    def run_checked(
        self,
        cmd: Iterable[object],
        *,
        label: str,
        tool_name: str,
        timeout_s: int | float | None,
        timeout_mode: str = "absolute",
        accepted_returncodes: tuple[int, ...] = (0,),
    ) -> bool:
        result = self.capture(
            cmd,
            label=label,
            timeout_s=timeout_s,
            timeout_mode=timeout_mode,
        )
        returncode = int(result.returncode)
        if returncode in accepted_returncodes:
            if returncode != 0:
                self._log(
                    f"⚠️ {tool_name} meldete Warnungen (rc={returncode}); Ausgabe wird weiter geprüft.",
                    "warn",
                )
            return True

        self._temp_state.failure_stage = label
        self._temp_state.failure_reason = f"{label}: {tool_name} fehlgeschlagen (rc={returncode})"
        self._log_tool_failure_fn(
            result,
            label=label,
            log=self._log,
            tool_name=tool_name,
        )
        return False

    def run_hdrplus(
        self,
        cmd: Iterable[object],
        *,
        label: str,
        tool_name: str,
        accepted_returncodes: tuple[int, ...] = (0,),
    ) -> bool:
        return self.run_checked(
            cmd,
            label=label,
            tool_name=tool_name,
            timeout_s=get_timeout("hdrplus_tool"),
            accepted_returncodes=accepted_returncodes,
        )

    def run_hdrplus_rc(self, cmd: Iterable[object], *, allow_error: bool = False) -> int:
        command = [str(part) for part in cmd]
        label = "HDR10+: Metadata-Nachpruefung"
        result = self.capture(
            command,
            label=label,
            timeout_s=get_timeout("hdrplus_tool"),
        )
        if not result.ok:
            tool_name = Path(command[0]).name if command else "hdr10plus_tool"
            self._temp_state.failure_stage = label
            self._temp_state.failure_reason = (
                f"{label}: {tool_name} fehlgeschlagen (rc={int(result.returncode)})"
            )
            if not allow_error:
                self._log_tool_failure_fn(
                    result,
                    label=label,
                    log=self._log,
                    tool_name=tool_name,
                )
        return int(result.returncode)

    def run_mux(
        self,
        cmd: Iterable[object],
        *,
        label: str,
        tool_name: str,
        accepted_returncodes: tuple[int, ...] = (0,),
    ) -> bool:
        return self.run_checked(
            cmd,
            label=label,
            tool_name=tool_name,
            timeout_s=get_timeout("worker_media_process"),
            timeout_mode="inactivity",
            accepted_returncodes=accepted_returncodes,
        )
