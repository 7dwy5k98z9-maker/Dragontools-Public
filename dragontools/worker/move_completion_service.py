# -*- coding: utf-8 -*-
"""Abschlussphase eines bereits erfolgreich installierten Video-Moves."""
from __future__ import annotations

from dataclasses import dataclass
import inspect
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
        move_sidecars: Callable[..., dict],
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

    def _call_move_sidecars(
        self,
        sidecar_key: str,
        target_dir: str,
        dest_path: str,
        source_video_path: str,
        staged_paths: list[str] | tuple[str, ...] | set[str] | None = None,
        force_nfo_overwrite: bool = False,
    ) -> dict:
        """Call the companion contract while preserving legacy adapters.

        ``sidecar_key`` identifies the map entry that contains the companion paths.
        ``source_video_path`` preserves the original video stem for rename+recovery
        so ``Film.de.srt`` can still be rebased to a committed ``Film_01.mkv``.
        """
        try:
            signature = inspect.signature(self._move_sidecars)
            params = list(signature.parameters.values())
            accepts_varargs = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params)
            positional = [
                p for p in params
                if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
            ]
        except (TypeError, ValueError):
            accepts_varargs = True
            positional = []
        if accepts_varargs or len(positional) >= 6:
            return self._move_sidecars(
                sidecar_key,
                target_dir,
                dest_path,
                source_video_path,
                staged_paths,
                force_nfo_overwrite,
            )
        if len(positional) >= 5:
            return self._move_sidecars(
                sidecar_key, target_dir, dest_path, source_video_path, staged_paths
            )
        if len(positional) >= 4:
            return self._move_sidecars(
                sidecar_key, target_dir, dest_path, source_video_path
            )
        if len(positional) >= 3:
            return self._move_sidecars(sidecar_key, target_dir, dest_path)
        return self._move_sidecars(sidecar_key, target_dir)

    def complete(
        self,
        *,
        journal_source: str,
        sidecar_key: str,
        target_dir: str,
        original_source: str,
        move_result: dict,
        staged_sidecar_paths: list[str] | tuple[str, ...] | set[str] | None = None,
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

        sidecar_result = self._call_move_sidecars(
            sidecar_key,
            target_dir,
            dest_path,
            str(original_source or sidecar_key),
            staged_sidecar_paths,
            bool(move_result.get("episode_identity_replacement")),
        )
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
