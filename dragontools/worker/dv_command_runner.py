# -*- coding: utf-8 -*-
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from .command_formatting import command_to_log_string, is_ffmpeg_command
from .tool_runner import run_tool


class DVCommandRunner:
    """Einheitliche Tool-Ausführung für die DV-Stufen.

    Der Runner kennt keine DV-Fachlogik. Er sorgt ausschließlich für Timeout,
    ``-nostdin`` bei ffmpeg, Windows-Fensterunterdrückung und konsistentes
    Logging. Dadurch verschwinden die verschachtelten ``run_cmd``-Closures aus
    ``DVProcessingPipeline.run``.
    """

    def __init__(
        self,
        *,
        log: Callable[[str, str], None],
        verbose_log: Callable[[str], None],
        no_window_kwargs: Callable[[], dict],
        temp_state=None,
        worker=None,
    ) -> None:
        self._log = log
        self._vlog = verbose_log
        self._no_window_kwargs = no_window_kwargs
        self._temp_state = temp_state
        self._worker = worker

    def _reset_command_diagnostics(self, command: list[str], label: str) -> None:
        state = self._temp_state
        if state is None:
            return
        # Ein neues Tool darf keine stderr-Reste eines vorherigen, erfolgreich
        # abgefangenen Fallbacks in einen späteren Fehlerbericht verschleppen.
        state.stderr = ""
        state.failure_reason = ""
        state.failure_stage = label
        state.last_tool = Path(command[0]).name if command else ""
        state.last_command = command_to_log_string(command) if command else ""

    def _record_failure(
        self,
        *,
        command: list[str],
        label: str,
        reason: str,
        output: str = "",
    ) -> None:
        state = self._temp_state
        if state is None:
            return
        state.record_failure(
            reason=reason,
            stage=label,
            tool=Path(command[0]).name if command else "",
            command=command_to_log_string(command) if command else "",
            output=output,
        )

    def run(
        self,
        cmd,
        *,
        allow_error: bool = False,
        return_process: bool = False,
        timeout: int | float = 3600,
        label: str = "DV-Tool",
    ):
        command = list(cmd)
        if not command:
            self._log("❌ [DV] Leerer Tool-Befehl wurde verworfen.", "error")
            return None if return_process else 1
        if is_ffmpeg_command(command[0]) and "-nostdin" not in command:
            command = [command[0], "-nostdin"] + command[1:]

        started = time.monotonic()
        self._reset_command_diagnostics(command, label)
        self._vlog(f"[DV CMD] {command_to_log_string(command)}")
        try:
            result = run_tool(
                command,
                label=label,
                timeout_s=timeout,
                timeout_mode="absolute",
                worker=self._worker,
                log=self._log,
            )
        except (OSError, ValueError) as exc:
            reason = f"{label}: {Path(command[0]).name} konnte nicht ausgeführt werden: {exc}"
            self._record_failure(command=command, label=label, reason=reason, output=str(exc))
            self._log(
                f"❌ [DV] Tool konnte nicht ausgeführt werden: {Path(command[0]).name} – {exc}",
                "error",
            )
            return None if return_process else 1

        elapsed = time.monotonic() - started
        if result.aborted:
            reason = f"{label}: durch Benutzer abgebrochen"
            self._record_failure(command=command, label=label, reason=reason, output=result.combined_output)
            return result if return_process else 130
        if result.timed_out:
            tool = Path(command[0]).name
            reason = f"{label}: Timeout nach {elapsed:.0f}s ({tool})"
            self._record_failure(command=command, label=label, reason=reason, output=result.combined_output)
            self._log(
                f"❌ [DV] Timeout ({timeout}s) bei '{tool}' nach {elapsed:.0f}s – Prozess abgebrochen.",
                "error",
            )
            return result if return_process else 1

        rc = result.returncode
        if rc != 0:
            tool = Path(command[0]).name
            err_text = (result.stderr or result.stdout or "").strip()
            tail_lines = [line for line in err_text.splitlines() if line.strip()][-20:]
            tail = "\n".join(tail_lines)
            reason = f"{label}: {tool} fehlgeschlagen (rc={rc})"
            if (
                tool.casefold().startswith("dovi_tool")
                and "unknown metadata block found" in tail.casefold()
            ):
                reason += (
                    "; dovi_tool konnte im verarbeiteten Dolby-Vision-RPU einen "
                    "CM-v4-Metadatenblock nicht interpretieren. Ursache kann eine "
                    "abweichende/fehlende Profilnormalisierung oder ein tatsächlich "
                    "inkompatibler Metadatenblock sein"
                )
            self._record_failure(
                command=command,
                label=label,
                reason=reason,
                output=tail,
            )
            if not allow_error:
                self._log(f"❌ DV-Fehler bei {tool} (rc={rc}, {elapsed:.1f}s)", "error")
                for line in tail_lines[-8:]:
                    self._log(f"  stderr: {line}", "error")
        else:
            self._vlog(f"[DV] {label} OK (rc={rc}, {elapsed:.1f}s)")
        return result if return_process else rc

    def adapter(
        self,
        *,
        timeout: int | float,
        label: str,
        default_return_process: bool = False,
    ):
        """Erzeugt den von den vorhandenen DV-Services erwarteten Callback."""
        def _run(cmd, allow_error=False, return_process=None, **_):
            effective_return_process = (
                default_return_process
                if return_process is None
                else bool(return_process)
            )
            return self.run(
                cmd,
                allow_error=allow_error,
                return_process=effective_return_process,
                timeout=timeout,
                label=label,
            )

        return _run
