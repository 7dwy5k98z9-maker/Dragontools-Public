# -*- coding: utf-8 -*-
"""Per-Datei-Fehlergrenze und Quellbild-Preflight für ConverterThread."""
from __future__ import annotations

import traceback
from pathlib import Path
from types import SimpleNamespace

from ..core.error_report import write_conversion_error_report
from ..core.models import normalize_override_dict
from .source_visual_check import source_visual_settings_from_qsettings


class ConverterFileExecutor:
    """Führt genau eine Queue-Datei über den bereits verdrahteten Workflow aus."""

    def __init__(self, worker) -> None:
        self._worker = worker

    def execute(self, input_path: str) -> bool:
        worker = self._worker
        if worker._services.workflow_runner is None:
            raise RuntimeError(
                "convert_file() aufgerufen bevor run() den Worker initialisiert hat. "
                "ConverterThread muss über QThread.start() gestartet werden."
            )
        try:
            worker.emit_file_result(input_path, input_path, "⏳")
            worker.emit_file_progress(input_path, 0)
            override = normalize_override_dict(worker._job_state.file_overrides.get(input_path))
            if not self._check_source_visual_quality(input_path, override):
                return False
            return worker._services.workflow_runner.run(input_path, override)
        except Exception:
            traceback_text = traceback.format_exc()
            worker._session_state.keep_verbose_log = True
            worker.log(
                f"❌ Unbehandelte Ausnahme in convert_file() bei {Path(input_path).name}",
                "error",
            )
            worker._verbose_logger.write(traceback_text)
            try:
                report_path = write_conversion_error_report(
                    ctx=SimpleNamespace(
                        input_path=input_path,
                        pipeline="",
                        container="",
                        strategy_name="convert_file",
                        replace_original=worker._job_state.overwrite_original,
                        strip_only=worker._job_state.strip_only,
                        file_override=normalize_override_dict(
                            worker._job_state.file_overrides.get(input_path)
                        ),
                    ),
                    reason="Unbehandelte Ausnahme im Converter-Worker.",
                    tool_output=getattr(worker._temp_state, "stderr", "") or "",
                    log_file=getattr(worker._logger, "log_file", None),
                    traceback_text=traceback_text,
                )
                worker._session_state.failure_details[input_path] = {
                    "message": "Unbehandelte Ausnahme im Converter-Worker.",
                    "error_report": report_path,
                    "pipeline": "",
                    "container": "",
                    "strategy": "convert_file",
                }
                worker.log(f"Fehlerbericht: {report_path}", "error")
            except Exception as report_exc:
                worker.log(
                    f"Fehlerbericht konnte nicht erstellt werden: {report_exc}",
                    "error",
                )
            worker._services.result.fail_unhandled(input_path)
            return False

    def _check_source_visual_quality(self, input_path: str, override: dict) -> bool:
        worker = self._worker
        if override.get("allow_suspicious_source"):
            worker.log("Quellbildprüfung: Datei per Override freigegeben.", "warn")
            return True

        service = worker._services.source_visual_check
        if service is None:
            return True

        settings = source_visual_settings_from_qsettings(worker.settings)
        if not settings.enabled:
            return True

        worker.log(
            "🔎 Quellbildprüfung startet "
            f"({settings.interval_percent}%-Intervalle, {settings.sample_duration_s}s, "
            f"{settings.fps} fps).",
            "info",
        )
        result = service.check(input_path, settings)
        for line in result.report_lines(include_ok=result.blocked):
            worker.log(line, "warn" if result.blocked else "info")

        if not result.blocked:
            return True

        reason = (
            "Quellbild unplausibel: "
            f"{result.suspicious_count}/{len(result.probes)} Prüfpunkte auffällig. "
            "Die Datei wurde nicht konvertiert. Per Rechtsklick kann sie mit "
            "'Quellbildprüfung übergehen' erneut freigegeben werden."
        )
        worker._services.result.skip(input_path, reason)
        return False
