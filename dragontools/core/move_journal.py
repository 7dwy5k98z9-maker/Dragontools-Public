# -*- coding: utf-8 -*-
"""Persistentes Journal für nicht abgeschlossene Verschiebevorgänge."""
from __future__ import annotations
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from .json_io import atomic_write_json as _atomic_write_json
from .move_journal_contracts import MOVE_JOURNAL_VERSION, JOURNAL_FILE_PREFIX, ARCHIVE_DIR_NAME, TERMINAL_OK, MoveJournalWriteError
from .move_journal_storage import (move_journal_dir, active_move_journal_path, new_move_journal_path, list_move_journal_paths, read_move_journal_path, read_active_move_journals, read_active_move_journal, archive_move_journal_path, archive_active_move_journal)
from .move_journal_resume import build_move_resume_plan, format_unfinished_move_summary
from .move_journal_utils import (_remove_path, _normalize_status, _has_retryable_files, _json_safe_dict, _dedupe, _unique_archive_path, _now)

_LOG = logging.getLogger(__name__)

def recover_active_move_backups(root: str | Path | None = None) -> dict[str, int]:
    totals = {
        "restored": 0,
        "kept": 0,
        "failed": 0,
        "completed": 0,
        "cleaned": 0,
        "ambiguous": 0,
    }
    for data in read_active_move_journals(root):
        path_text = str(data.get("_journal_path") or "")
        if not path_text:
            continue
        path = Path(path_text)
        result = recover_interrupted_backups(data)
        for key in totals:
            totals[key] += int(result.get(key, 0) or 0)
        if any(
            int(result.get(key, 0) or 0)
            for key in ("restored", "failed", "completed", "cleaned", "ambiguous")
        ):
            try:
                _atomic_write_json(path, data)
            except OSError as exc:
                _LOG.warning("Move-Journal konnte nach Recovery nicht geschrieben werden: %s (%s)", path, exc)
                totals["failed"] += 1
                continue
        if data.get("active") and not _has_retryable_files(data):
            data["active"] = False
            data["status"] = "completed"
            data["finished_at"] = _now()
            data["updated_at"] = data["finished_at"]
            try:
                _atomic_write_json(path, data)
                archive_move_journal_path(path, status="completed_after_crash")
            except OSError as exc:
                _LOG.warning("Abgeschlossenes Move-Journal konnte nicht archiviert werden: %s (%s)", path, exc)
                totals["failed"] += 1
    return totals

def recover_interrupted_backups(data: dict[str, Any]) -> dict[str, int]:
    """Stellt sichere Backups wieder her und erkennt Crash-Erfolge.

    Ein laufender Move kann nach dem Kopieren/Hardlinken crashen, bevor das
    Journal finalisiert wurde. Ein Commit gilt nur dann als eindeutig belegt,
    wenn das Ziel existiert und die Quelle nicht mehr existiert. Existieren
    Quelle und Ziel gleichzeitig, bleibt die Recovery absichtlich konservativ:
    Altbestand-Backups werden erhalten und der Zustand als mehrdeutig markiert.
    """
    restored = 0
    kept = 0
    failed = 0
    completed = 0
    cleaned = 0
    ambiguous = 0
    changed = False
    files = data.get("files") if isinstance(data.get("files"), dict) else {}
    for source_text, row in files.items():
        if not isinstance(row, dict):
            continue
        dest = Path(str(row.get("dest_path") or "")) if row.get("dest_path") else None
        source = Path(str(source_text)) if source_text else None
        source_exists = bool(source and source.exists())
        dest_exists = bool(dest and dest.exists())
        status = _normalize_status(row.get("status"))
        phase = str(row.get("phase") or "")

        cleanup_pending = bool(row.get("cleanup_pending"))
        if cleanup_pending and dest_exists and source_exists and source is not None:
            try:
                _remove_path(source)
                source_exists = False
                row["cleanup_pending"] = False
                row["cleanup_message"] = ""
                row["status"] = "running" if phase == "sidecars_pending" else "ok"
                if phase != "sidecars_pending":
                    row["phase"] = "completed"
                row["message"] = "Cleanup nach Crash erfolgreich abgeschlossen"
                row["finished_at"] = row.get("finished_at") or _now()
                cleaned += 1
                changed = True
            except OSError:
                failed += 1

        commit_proven = dest_exists and not source_exists
        ambiguous_state = dest_exists and source_exists

        if status in {"running", "warn"} and commit_proven and phase != "sidecars_pending":
            row["status"] = "ok"
            row["finished_at"] = row.get("finished_at") or _now()
            row["message"] = str(row.get("message") or "Nach Crash als abgeschlossen erkannt")
            row.pop("recovery_status", None)
            completed += 1
            changed = True
        elif ambiguous_state:
            recovery_message = (
                "Recovery mehrdeutig: Quelle und Ziel existieren; "
                "Altbestand-Backup bleibt erhalten und es erfolgt keine automatische Bereinigung."
            )
            if row.get("recovery_status") != "ambiguous_source_and_destination":
                row["recovery_status"] = "ambiguous_source_and_destination"
                changed = True
            if row.get("message") != recovery_message:
                row["message"] = recovery_message
                changed = True
            ambiguous += 1

        pairs = row.get("backup_pairs") if isinstance(row.get("backup_pairs"), list) else []
        remaining: list[dict[str, str]] = []
        for pair in pairs:
            if not isinstance(pair, dict):
                continue
            original_text = str(pair.get("original") or "")
            backup_text = str(pair.get("backup") or "")
            if not original_text or not backup_text:
                continue
            original = Path(original_text)
            backup = Path(backup_text)
            if not backup.exists():
                changed = True
                continue
            if commit_proven:
                try:
                    _remove_path(backup)
                    cleaned += 1
                    changed = True
                except OSError:
                    failed += 1
                    remaining.append({"original": original_text, "backup": backup_text})
                continue
            if ambiguous_state:
                kept += 1
                remaining.append({"original": original_text, "backup": backup_text})
                continue
            if original.exists():
                kept += 1
                remaining.append({"original": original_text, "backup": backup_text})
                continue
            try:
                os.replace(str(backup), str(original))
                restored += 1
                changed = True
            except OSError:
                failed += 1
                remaining.append({"original": original_text, "backup": backup_text})
        row["backup_pairs"] = remaining

    if changed or restored or failed:
        data["updated_at"] = _now()
    return {
        "restored": restored,
        "kept": kept,
        "failed": failed,
        "completed": completed,
        "cleaned": cleaned,
        "ambiguous": ambiguous,
    }

class MoveJournal:
    def __init__(
        self,
        path: str | Path | None = None,
        *,
        on_write_error: Callable[[str], None] | None = None,
    ) -> None:
        self.path = Path(path) if path is not None else active_move_journal_path()
        self.data: dict[str, Any] = {}
        self._lock = threading.RLock()
        self._on_write_error = on_write_error

    @classmethod
    def start(
        cls,
        *,
        files: list[str],
        target_paths: dict[str, str] | None = None,
        planned_targets: dict | None = None,
        sidecar_outputs_by_video: dict[str, list[str]] | None = None,
        conflict_mode: str = "skip",
        log_file: str | None = None,
        root: str | Path | None = None,
        on_write_error: Callable[[str], None] | None = None,
    ) -> "MoveJournal":
        journal = cls(new_move_journal_path(root), on_write_error=on_write_error)
        now = _now()
        run_id = journal.path.stem.removeprefix(JOURNAL_FILE_PREFIX)
        journal.data = {
            "format": "DragonToolsMoveJournal",
            "format_version": MOVE_JOURNAL_VERSION,
            "active": True,
            "status": "running",
            "run_id": run_id,
            "started_at": now,
            "updated_at": now,
            "pid": os.getpid(),
            "log_file": str(log_file or ""),
            "conflict_mode": str(conflict_mode or "skip"),
            "target_paths": _json_safe_dict(target_paths or {}),
            "planned_targets": _json_safe_dict(planned_targets or {}),
            "sidecar_outputs_by_video": _json_safe_dict(sidecar_outputs_by_video or {}),
            "current_file": "",
            "files": {
                str(path): {
                    "status": "queued",
                    "target_dir": "",
                    "dest_path": "",
                    "message": "",
                    "phase": "queued",
                    "backup_pairs": [],
                    "cleanup_pending": False,
                    "cleanup_message": "",
                    "started_at": "",
                    "finished_at": "",
                }
                for path in files
            },
        }
        journal._write()
        return journal

    def start_file(self, source_path: str, *, target_dir: str = "", dest_path: str = "") -> None:
        with self._lock:
            row = self._row(source_path)
            row["status"] = "running"
            row["phase"] = "video_pending"
            row["target_dir"] = str(target_dir or row.get("target_dir") or "")
            row["dest_path"] = str(dest_path or row.get("dest_path") or "")
            row["started_at"] = row.get("started_at") or _now()
            self.data["current_file"] = str(source_path)
            self._touch()

    def set_destination(self, source_path: str, *, target_dir: str, dest_path: str) -> None:
        with self._lock:
            row = self._row(source_path)
            row["target_dir"] = str(target_dir or "")
            row["dest_path"] = str(dest_path or "")
            self._touch()

    def set_backups(self, source_path: str, pairs: list[dict[str, str]]) -> None:
        with self._lock:
            row = self._row(source_path)
            row["backup_pairs"] = [
                {"original": str(p.get("original") or ""), "backup": str(p.get("backup") or "")}
                for p in pairs
                if isinstance(p, dict)
            ]
            self._touch()

    def clear_backups(self, source_path: str) -> None:
        with self._lock:
            row = self._row(source_path)
            if row.get("backup_pairs"):
                row["backup_pairs"] = []
                self._touch()


    def set_cleanup_pending(self, source_path: str, *, message: str) -> None:
        with self._lock:
            row = self._row(source_path)
            row["cleanup_pending"] = True
            row["cleanup_message"] = str(message or "")
            row["status"] = "warn"
            row["message"] = str(message or "")
            self._touch()

    def clear_cleanup_pending(self, source_path: str) -> None:
        with self._lock:
            row = self._row(source_path)
            row["cleanup_pending"] = False
            row["cleanup_message"] = ""
            self._touch()

    def mark_video_committed(
        self,
        source_path: str,
        *,
        dest_path: str,
        message: str = "",
    ) -> None:
        """Persistiert den Video-Commit, bevor Companion-Dateien beginnen."""
        with self._lock:
            row = self._row(source_path)
            row["status"] = "running"
            row["phase"] = "sidecars_pending"
            if dest_path:
                row["dest_path"] = str(dest_path)
            row["message"] = str(message or "")
            self._touch()

    def finish_file(
        self,
        source_path: str,
        *,
        status: str,
        dest_path: str = "",
        message: str = "",
        phase: str | None = None,
    ) -> None:
        with self._lock:
            row = self._row(source_path)
            row["status"] = _normalize_status(status)
            if phase is not None:
                row["phase"] = str(phase or "")
            elif row["status"] in TERMINAL_OK:
                row["phase"] = "completed"
            if dest_path:
                row["dest_path"] = str(dest_path)
            row["message"] = str(message or "")
            row["finished_at"] = _now()
            if str(self.data.get("current_file") or "") == str(source_path):
                self.data["current_file"] = ""
            self._touch()

    def has_retryable_files(self) -> bool:
        return _has_retryable_files(self.data)

    def finish_run(self, *, status: str, keep_active: bool) -> None:
        with self._lock:
            self.data["status"] = str(status or "incomplete")
            self.data["active"] = bool(keep_active)
            self.data["finished_at"] = _now()
            self._touch()
            if not keep_active:
                self._archive_completed()

    def _row(self, source_path: str) -> dict[str, Any]:
        files = self.data.setdefault("files", {})
        return files.setdefault(
            str(source_path),
            {
                "status": "queued",
                "target_dir": "",
                "dest_path": "",
                "message": "",
                "phase": "queued",
                "backup_pairs": [],
                "cleanup_pending": False,
                "cleanup_message": "",
                "started_at": "",
                "finished_at": "",
            },
        )

    def _touch(self) -> None:
        self.data["updated_at"] = _now()
        self._write()

    def _write(self) -> None:
        try:
            _atomic_write_json(self.path, self.data)
        except (OSError, TypeError, ValueError) as exc:
            message = f"Move-Journal konnte nicht geschrieben werden: {self.path} ({exc})"
            _LOG.exception(message)
            if self._on_write_error:
                try:
                    self._on_write_error(message)
                except Exception as callback_exc:
                    _LOG.warning("Move-Journal-Fehlercallback fehlgeschlagen: %s", callback_exc)
            raise MoveJournalWriteError(message) from exc

    def _archive_completed(self) -> None:
        try:
            archive_dir = self.path.parent / ARCHIVE_DIR_NAME
            archive_dir.mkdir(parents=True, exist_ok=True)
            run_id = str(self.data.get("run_id") or datetime.now().strftime("%Y%m%d_%H%M%S"))
            archive = _unique_archive_path(archive_dir / f"{run_id}_{self.data.get('status', 'completed')}.json")
            _atomic_write_json(archive, self.data)
            self.path.unlink(missing_ok=True)
        except (OSError, TypeError, ValueError) as exc:
            message = f"Move-Journal konnte nicht archiviert werden: {self.path} ({exc})"
            _LOG.exception(message)
            if self._on_write_error:
                try:
                    self._on_write_error(message)
                except Exception as callback_exc:
                    _LOG.warning("Move-Journal-Fehlercallback fehlgeschlagen: %s", callback_exc)
            raise MoveJournalWriteError(message) from exc
