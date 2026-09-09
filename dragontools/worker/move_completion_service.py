# -*- coding: utf-8 -*-
"""Abschlussphase eines bereits erfolgreich installierten Video-Moves."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class MoveCompletionOutcome:
    """Ergebnis der Companion-/Postprocess-Phase eines Video-Moves."""

    error: bool
    dest_path: str


class MoveCompletionService:
    """Hält Companion-Commit, DB-Reihenfolge und Journalabschluss konsistent."""

    def __init__(
        self,
        *,
        journal,
        move_sidecars: Callable[[str, str], dict],
        record_media_library_move: Callable[[str, dict | None], None],
        append_move_report: Callable[[dict | None], None],
        log: Callable[[str, str], None],
    ) -> None:
        self._journal = journal
        self._move_sidecars = move_sidecars
        self._record_media_library_move = record_media_library_move
        self._append_move_report = append_move_report
        self._log = log

    def companion_resume_result(
        self,
        *,
        video_path: str,
        target_dir: str,
        original_source: str,
    ) -> tuple[bool, dict]:
        """Erzeugt für Recovery ein Videoresultat ohne erneuten Video-Move."""
        dest_path = str(Path(video_path))
        ok = Path(dest_path).exists()
        result = {
            "kind": "video",
            "name": Path(dest_path).name,
            "source_path": str(original_source),
            "target_dir": str(target_dir),
            "dest_path": dest_path,
            "ok": ok,
            "recovered_companion_only": True,
        }
        if ok:
            self._log(
                "↻ Move-Recovery: Video bereits committed, Companion-Dateien werden "
                f"fortgesetzt: {Path(dest_path).name}",
                "info",
            )
        return ok, result

    def complete(
        self,
        *,
        journal_source: str,
        sidecar_key: str,
        target_dir: str,
        original_source: str,
        move_result: dict,
    ) -> MoveCompletionOutcome:
        cleanup_pending = bool(move_result.get("cleanup_pending"))
        self._append_move_report(move_result)
        dest_path = str(
            move_result.get("dest_path") or (Path(target_dir) / Path(sidecar_key).name)
        )
        self._journal.mark_video_committed(
            journal_source,
            dest_path=dest_path,
            message=str(move_result.get("cleanup_message") or "") if cleanup_pending else "",
        )

        sidecar_result = self._move_sidecars(sidecar_key, target_dir)
        if not bool(sidecar_result.get("ok", True)):
            failed_count = int(sidecar_result.get("failed", 0) or 0)
            message = f"{failed_count} Companion-Datei(en) konnten nicht abgeschlossen werden"
            self._journal.finish_file(
                journal_source,
                status="warn",
                dest_path=dest_path,
                message=message,
                phase="sidecars_pending",
            )
            self._log(f"⚠️ {message}: {Path(dest_path).name}", "warn")
            return MoveCompletionOutcome(error=True, dest_path=dest_path)

        # DB/Mediathek erst nach erfolgreichem Companion-Commit.
        self._record_media_library_move(str(original_source), move_result)
        self._journal.finish_file(
            journal_source,
            status="warn" if cleanup_pending else "ok",
            dest_path=dest_path,
            message=str(move_result.get("cleanup_message") or "") if cleanup_pending else "",
            phase="cleanup_pending" if cleanup_pending else "completed",
        )
        return MoveCompletionOutcome(error=cleanup_pending, dest_path=dest_path)
