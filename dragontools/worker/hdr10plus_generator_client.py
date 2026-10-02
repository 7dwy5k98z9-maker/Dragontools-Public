# -*- coding: utf-8 -*-
"""Stable DragonTools client for the optional external HDR10+ generator."""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

from .tool_process_lifecycle import TimeoutMode
from .tool_runner import ToolRunResult, run_tool


DEFAULT_ANALYZE_INACTIVITY_TIMEOUT_S = 600


@dataclass(frozen=True, slots=True)
class HDR10PlusGeneratorResult:
    success: bool
    returncode: int
    command: tuple[str, ...] = ()
    version: str = ""
    error: str = ""
    message: str = ""
    frames: int | None = None
    scenes: int | None = None
    frame_count_source: str = ""
    frame_count_reliability: str = ""
    transfer: str = ""
    input: str = ""
    output: str = ""
    aborted: bool = False
    timed_out: bool = False
    diagnostic_output_preserved: bool = False
    payload: dict[str, Any] = field(default_factory=dict)


def generator_executable_available(executable: str | Path | None) -> bool:
    value = str(executable or "").strip()
    if not value:
        return False
    try:
        if Path(value).is_file():
            return True
    except OSError:
        pass
    return bool(shutil.which(value))


class HDR10PlusGeneratorClient:
    """Invoke the generator without parsing human-readable log messages.

    Contract:
      ``<exe> --version`` -> one JSON object on stdout
      ``<exe> analyze --input <path> --output <json>`` -> one JSON object

    The generated JSON file is owned by the caller/pipeline.  This client never
    remuxes or calls ``hdr10plus_tool``.
    """

    def __init__(
        self,
        executable: str,
        *,
        worker=None,
        log: Callable[[str, str], None] | None = None,
        run_tool_fn: Callable[..., ToolRunResult] = run_tool,
        ffmpeg_path: str | Path | None = None,
        ffprobe_path: str | Path | None = None,
    ) -> None:
        self.executable = str(executable or "")
        self.ffmpeg_path = str(ffmpeg_path or "").strip()
        self.ffprobe_path = str(ffprobe_path or "").strip()
        self._worker = worker
        self._log = log
        self._run_tool = run_tool_fn

    def build_version_command(self) -> list[str]:
        return [self.executable, "--version"]

    def build_analyze_command(self, input_path: str | Path, output_path: str | Path) -> list[str]:
        command = [
            self.executable,
            "analyze",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ]
        # DragonTools passes its resolved tool paths explicitly. Standalone use
        # remains portable because the generator CLI falls back to PATH when
        # these optional arguments are omitted.
        if self.ffmpeg_path:
            command.extend(["--ffmpeg", self.ffmpeg_path])
        if self.ffprobe_path:
            command.extend(["--ffprobe", self.ffprobe_path])
        return command

    def probe_version(self, *, timeout_s: int | float = 15) -> HDR10PlusGeneratorResult:
        return self._invoke(self.build_version_command(), timeout_s=timeout_s, label="HDR10+ Generator Version")

    def analyze(
        self,
        input_path: str | Path,
        output_path: str | Path,
        *,
        timeout_s: int | float | None = DEFAULT_ANALYZE_INACTIVITY_TIMEOUT_S,
    ) -> HDR10PlusGeneratorResult:
        output = Path(output_path)
        output.unlink(missing_ok=True)
        result = self._invoke(
            self.build_analyze_command(input_path, output),
            timeout_s=timeout_s,
            label="HDR10+ Generator Analyse",
            activity_file=output,
            timeout_mode="inactivity",
        )
        if not result.success:
            payload, _error = self._read_output_payload(output)
            if payload is not None:
                if callable(self._log):
                    self._log(
                        "⚠️ HDR10+-Generator meldete einen Fehler, hat aber eine gültige JSON erzeugt; "
                        "sie bleibt als untrusted Diagnoseartefakt erhalten.",
                        "warn",
                    )
                return replace(result, diagnostic_output_preserved=True)
            output.unlink(missing_ok=True)
            return result
        if not output.is_file() or output.stat().st_size <= 0:
            return self._failed_from(result, "OUTPUT_MISSING", "Generator meldet Erfolg, aber hdr10plus.json fehlt oder ist leer.")
        payload, parse_error = self._read_output_payload(output)
        if payload is None:
            output.unlink(missing_ok=True)
            return self._failed_from(result, "OUTPUT_INVALID_JSON", parse_error)
        return result

    def _invoke(
        self,
        command: list[str],
        *,
        timeout_s: int | float | None,
        label: str,
        activity_file: Path | None = None,
        timeout_mode: TimeoutMode = "absolute",
    ) -> HDR10PlusGeneratorResult:
        if not generator_executable_available(self.executable):
            return HDR10PlusGeneratorResult(
                False,
                127,
                tuple(command),
                error="TOOL_NOT_FOUND",
                message=f"Dragon HDR10+ Generator nicht gefunden: {self.executable}",
            )
        tool_result = self._run_tool(
            command,
            label=label,
            timeout_s=timeout_s,
            worker=self._worker,
            log=self._log,
            abort_on_request=True,
            activity_file=str(activity_file) if activity_file is not None else None,
            timeout_mode=timeout_mode,
            stderr_line=self._progress_line if label == "HDR10+ Generator Analyse" else None,
        )
        if tool_result.aborted:
            return HDR10PlusGeneratorResult(
                False, tool_result.returncode, tuple(command), error="ABORTED",
                message="HDR10+-Generator wurde abgebrochen.", aborted=True,
                timed_out=tool_result.timed_out,
            )
        if tool_result.timed_out:
            return HDR10PlusGeneratorResult(
                False, tool_result.returncode, tuple(command), error="TIMEOUT",
                message="HDR10+-Generator hat das Zeitlimit überschritten.", timed_out=True,
            )

        payload, parse_error = self._parse_stdout(tool_result.stdout)
        if parse_error:
            return HDR10PlusGeneratorResult(
                False,
                tool_result.returncode,
                tuple(command),
                error="INVALID_JSON_RESPONSE",
                message=parse_error,
            )

        success = payload.get("success") is True and tool_result.returncode == 0
        error = str(payload.get("error") or ("GENERATOR_FAILED" if not success else ""))
        message = str(payload.get("message") or "")
        if tool_result.returncode != 0 and not message:
            message = f"Generator beendete sich mit Exitcode {tool_result.returncode}."
        return HDR10PlusGeneratorResult(
            success=success,
            returncode=tool_result.returncode,
            command=tuple(command),
            version=str(payload.get("version") or ""),
            error=error,
            message=message,
            frames=self._int_or_none(payload.get("frames")),
            scenes=self._int_or_none(payload.get("scenes")),
            frame_count_source=str(payload.get("frame_count_source") or ("analysis_actual" if payload.get("frames") is not None else "")),
            frame_count_reliability=str(payload.get("frame_count_reliability") or ("reliable" if payload.get("frames") is not None else "")),
            transfer=str(payload.get("transfer") or ""),
            input=str(payload.get("input") or ""),
            output=str(payload.get("output") or ""),
            payload=payload,
        )


    def _progress_line(self, line: str) -> None:
        text = str(line or "").strip()
        if not text:
            return
        if text.startswith("HDR10+ scan:"):
            if callable(self._log):
                self._log(f"🧠 {text}", "info")
            return
        if callable(self._log):
            self._log(f"HDR10+ Generator: {text}", "info")

    @staticmethod
    def _parse_stdout(stdout: str) -> tuple[dict[str, Any], str]:
        text = str(stdout or "").strip()
        if not text:
            return {}, "Generator hat keine maschinenlesbare JSON-Antwort auf stdout geliefert."
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            return {}, f"Generator-stdout ist kein gültiges JSON: {exc}"
        if not isinstance(payload, dict):
            return {}, "Generator-stdout muss genau ein JSON-Objekt enthalten."
        if not isinstance(payload.get("success"), bool):
            return {}, "Generator-JSON enthält kein boolesches Feld 'success'."
        return payload, ""

    @staticmethod
    def _int_or_none(value: object) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _read_output_payload(output: Path) -> tuple[dict[str, Any] | None, str]:
        try:
            if not output.is_file() or output.stat().st_size <= 0:
                return None, "Erzeugte HDR10+-Datei fehlt oder ist leer."
            payload = json.loads(output.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return None, f"Erzeugte HDR10+-Datei ist kein gültiges JSON: {exc}"
        if not isinstance(payload, dict):
            return None, "Erzeugte HDR10+-Datei muss ein JSON-Objekt enthalten."
        return payload, ""

    @staticmethod
    def _failed_from(result: HDR10PlusGeneratorResult, error: str, message: str) -> HDR10PlusGeneratorResult:
        return HDR10PlusGeneratorResult(
            False,
            result.returncode,
            result.command,
            version=result.version,
            error=error,
            message=message,
            aborted=result.aborted,
            timed_out=result.timed_out,
            diagnostic_output_preserved=result.diagnostic_output_preserved,
            payload=result.payload,
        )


__all__ = [
    "DEFAULT_ANALYZE_INACTIVITY_TIMEOUT_S",
    "HDR10PlusGeneratorClient",
    "HDR10PlusGeneratorResult",
    "generator_executable_available",
]
