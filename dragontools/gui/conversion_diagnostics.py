# -*- coding: utf-8 -*-
"""Qt-unabhängige Formatierung des laufenden Conversion-Worker-Zustands."""
from __future__ import annotations

from pathlib import Path


class ConversionDiagnosticsService:
    def __init__(self, *, state) -> None:
        self._state = state

    def report(self, worker) -> str:
        if worker is None:
            return "Kein laufender Job aktiv."
        if hasattr(worker, "diagnostic_snapshot"):
            try:
                snapshot = worker.diagnostic_snapshot()
            except Exception as exc:
                return f"Diagnose konnte nicht erstellt werden:\n{exc}"
        else:
            snapshot = {
                "type": "generic",
                "running": bool(worker.isRunning()) if hasattr(worker, "isRunning") else False,
                "paused": bool(getattr(worker, "_paused", False)),
                "abort_requested": bool(getattr(worker, "abort_requested", False)),
                "abort_type": getattr(worker, "abort_type", "") or "",
            }
        return self.format_snapshot(snapshot)

    def format_snapshot(self, snapshot: dict) -> str:
        lines: list[str] = []
        kind = str(snapshot.get("type") or "generic")
        running = "ja" if snapshot.get("running") else "nein"
        paused = "ja" if snapshot.get("paused") else "nein"
        abort = "ja" if snapshot.get("abort_requested") else "nein"
        abort_type = str(snapshot.get("abort_type") or "-")

        lines.append("Laufender Job - Diagnose")
        lines.append("")
        lines.append(f"Typ: {kind}")
        lines.append(
            f"Läuft: {running} | Pausiert: {paused} | "
            f"Abbruch angefordert: {abort} ({abort_type})"
        )
        current_log = str(snapshot.get("log_file") or self._state.current_log_path or "")
        if current_log:
            lines.append(f"Log-Datei: {current_log}")
        lines.append("")

        if kind == "parallel_converter":
            done = len(snapshot.get("done_files") or [])
            total = int(snapshot.get("total_files") or self._state.total_files or 0)
            active = int(snapshot.get("active_count") or 0)
            pending = list(snapshot.get("pending_files") or [])
            progress = int(snapshot.get("progress_percent") or 0)
            lines.append(
                f"Gesamt: {done}/{total} fertig | {active} aktiv | "
                f"{len(pending)} wartend | {progress}%"
            )
            lines.append("")
            lines.append("Aktive Dateien:")
            workers = list(snapshot.get("active_workers") or [])
            progress_by_file = dict(snapshot.get("file_progress") or {})
            if workers:
                for idx, child in enumerate(workers, start=1):
                    current = str(child.get("current_file") or "")
                    pct = progress_by_file.get(current)
                    pct_text = f" ({int(pct)}%)" if pct is not None else ""
                    lines.append(f"{idx}. {self.short_path(current)}{pct_text}")
                    pid = child.get("process_pid")
                    command = str(child.get("process_command") or "")
                    if pid:
                        lines.append(f"   Prozess: PID {pid}")
                    if command:
                        lines.append(f"   Kommando: {command}")
            else:
                lines.append("- keine aktive Datei")
            self.append_waiting_files(lines, pending)
            return "\n".join(lines)

        current = str(snapshot.get("current_file") or "")
        waiting = list(snapshot.get("waiting_files") or [])
        done_files = list(snapshot.get("done_files") or [])
        success = int(snapshot.get("success_count") or 0)
        errors = int(snapshot.get("error_count") or 0)
        total = int(snapshot.get("total_count") or self._state.total_files or 0)
        current_idx = int(snapshot.get("current_idx") or 0)
        lines.append(
            f"Gesamt: Datei {current_idx}/{total} | OK: {success} | "
            f"Fehler: {errors} | Erledigt: {len(done_files)}"
        )
        lines.append(f"Aktuell: {self.short_path(current)}")
        pid = snapshot.get("process_pid")
        command = str(snapshot.get("process_command") or "")
        if pid:
            lines.append(f"Prozess: PID {pid}")
        if command:
            lines.append(f"Kommando: {command}")
        self.append_waiting_files(lines, waiting)
        return "\n".join(lines)

    def append_waiting_files(self, lines: list[str], files: list[str], *, limit: int = 10) -> None:
        lines.append("")
        lines.append(f"Wartende Dateien: {len(files)}")
        for path in files[:limit]:
            lines.append(f"- {self.short_path(str(path))}")
        if len(files) > limit:
            lines.append(f"- ... plus {len(files) - limit} weitere")

    @staticmethod
    def short_path(path: str) -> str:
        if not path:
            return "-"
        try:
            return Path(path).name
        except (OSError, ValueError, TypeError):
            return str(path)
