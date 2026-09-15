"""Ausführung und transaktionaler Output-Commit des lossless MKV-Merge."""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from ..core.timeout_settings import get_timeout
from .merge_common import MergeUserAbortError
from .merge_output_verifier import MergeOutputVerifier
from .tool_runner import run_tool


class MergeExecutorMixin:
    """Führt einen bereits validierten Merge-Plan aus."""

    def _run_lossless_merge(self, plan: dict[str, Any]) -> bool:
        container = plan["target_container"]
        files = list(plan["files"])
        output_path = str(plan["output_path"])

        self._logger.file_start(
            1,
            1,
            output_path,
            "merge",
            None,
            "lossless",
            plan["tool"],
            q_label="Modus",
        )
        self.progress.emit(50)
        self.file_progress.emit(output_path, 50, "Merge läuft")

        if container == "mkv":
            return self._merge_mkv_lossless(files, output_path, infos=list(plan.get("infos") or []))

        self._log(f"Kein lossless Merge-Pfad für '.{container}' vorhanden.", "error")
        return False

    def _merge_mkv_lossless(self, files: list[str], output_path: str, *, infos: list[dict[str, Any]] | None = None) -> bool:
        output = Path(output_path)
        temp_output = output.with_name(f"{output.name}.__merge_tmp__")
        output.parent.mkdir(parents=True, exist_ok=True)
        if not self._remove_stale_temp(temp_output):
            return False

        command = [self.tools.mkvmerge, "-o", str(temp_output), files[0]]
        for path in files[1:]:
            command += ["+", path]

        self._log(f"Starte lossless MKV-Merge mit mkvmerge: {output.name}")
        start_ts = time.time()
        total_before = self._input_size(files)

        try:
            result = run_tool(
                command,
                label="mkvmerge",
                timeout_s=get_timeout("worker_media_process"),
                timeout_mode="inactivity",
                worker=self,
                log=self._log,
                merge_stderr=True,
                stdout_line=(
                    lambda line: self._log(f"mkvmerge: {line}")
                    if line.strip()
                    else None
                ),
            )
            if result.aborted:
                raise MergeUserAbortError("Abgebrochen")
            if result.timed_out:
                self._log(
                    "mkvmerge wurde wegen Inaktivitäts-Timeout abgebrochen.",
                    "error",
                )
                self._cleanup_partial_output(temp_output)
                return False
            if not result.ok:
                self._log(
                    f"mkvmerge fehlgeschlagen (Exitcode {result.returncode}).",
                    "error",
                )
                self._cleanup_partial_output(temp_output)
                return False
            if not temp_output.exists() or temp_output.stat().st_size <= 0:
                self._log("mkvmerge lieferte keine gültige Ausgabedatei.", "error")
                self._cleanup_partial_output(temp_output)
                return False
            if not self._verify_merge_output(temp_output, infos or []):
                self._cleanup_partial_output(temp_output)
                return False
            if output.exists() and output.resolve() != temp_output.resolve():
                self._log(
                    f"Zieldatei existiert bereits und wird nicht überschrieben: {output.name}",
                    "error",
                )
                self._cleanup_partial_output(temp_output)
                return False
            try:
                os.replace(str(temp_output), str(output))
            except Exception as exc:
                self._log(f"Finales Ersetzen der Zieldatei fehlgeschlagen: {exc}", "error")
                self._cleanup_partial_output(temp_output)
                return False

            self._logger.file_done(
                files[0],
                str(output),
                total_before,
                output.stat().st_size,
                time.time() - start_ts,
                overwritten=False,
                start_ts=start_ts,
            )
            self._log("Lossless MKV-Merge erfolgreich abgeschlossen.", "success")
            return True
        except MergeUserAbortError:
            self._cleanup_partial_output(temp_output)
            raise

    def _verify_merge_output(self, output: Path, infos: list[dict[str, Any]]) -> bool:
        if not infos:
            # Direkte Legacy-Aufrufe ohne Analyseplan bleiben kompatibel; der
            # normale Produktivpfad liefert immer infos und wird fail-closed geprüft.
            return True
        first = infos[0]
        expected_duration_s = sum(max(0.0, float(info.get("duration_s") or 0.0)) for info in infos)
        verifier = MergeOutputVerifier(ffprobe_path=str(self.tools.ffprobe))
        result = verifier.verify(
            output_path=str(output),
            expected_duration_ms=(int(expected_duration_s * 1000) if expected_duration_s > 0 else None),
            expected_audio_tracks=len(list(first.get("audio_structure") or [])),
            expected_subtitle_tracks=len(list(first.get("subtitle_structure") or [])),
        )
        if result.ok:
            return True
        details = "; ".join(result.messages) or "unbekannter Verifikationsfehler"
        self._log(f"Merge-Ausgabevalidierung fehlgeschlagen: {details}", "error")
        return False

    def _remove_stale_temp(self, temp_output: Path) -> bool:
        try:
            if temp_output.exists():
                temp_output.unlink()
            return True
        except Exception as exc:
            self._log(
                "Temporäre Merge-Datei konnte nicht entfernt werden "
                f"({temp_output.name}): {exc}",
                "error",
            )
            return False

    def _cleanup_partial_output(self, temp_output: Path) -> None:
        if not temp_output.exists():
            return
        try:
            temp_output.unlink()
            self._log(
                f"Partielle temporäre Merge-Datei entfernt: {temp_output.name}",
                "warn",
            )
        except Exception as exc:
            self._log(
                f"Cleanup-Warnung für temporäre Merge-Datei {temp_output.name}: {exc}",
                "warn",
            )

    @staticmethod
    def _input_size(files: list[str]) -> int:
        total = 0
        for path in files:
            try:
                total += Path(path).stat().st_size
            except OSError:
                pass
        return total
