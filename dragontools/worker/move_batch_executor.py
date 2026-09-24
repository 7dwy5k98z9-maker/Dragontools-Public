# -*- coding: utf-8 -*-
"""Batch execution for MoveThread without Qt/thread-state ownership."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from ..core.callback_dispatch import invoke_callback
from ..core.move_source_probe import probe_companions, probe_move_source
from .move_completion_service import MoveCompletionService


LogFn = Callable[[str, str], None]
MoveFn = Callable[..., bool]


def collect_move_files(paths: Iterable[str]) -> tuple[list[tuple[str, int]], int]:
    """Collect source sizes once for byte-based move progress calculation."""
    files: list[tuple[str, int]] = []
    total = 0
    for path in paths:
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        files.append((path, size))
        total += size
    return files, total


class MoveProgressTracker:
    """Translate copied bytes into percent and ETA callbacks."""

    def __init__(
        self,
        total_bytes: int,
        *,
        emit_progress: Callable[[int], None],
        emit_eta: Callable[[float], None],
    ) -> None:
        self._total = max(int(total_bytes), 1)
        self._emit_progress = emit_progress
        self._emit_eta = emit_eta
        self._bytes_done = 0
        self._started = time.time()

    def update(self, chunk_size: int) -> None:
        self._bytes_done += int(chunk_size)
        invoke_callback(self._emit_progress, min(int(self._bytes_done / self._total * 100), 99))
        elapsed = time.time() - self._started
        if elapsed <= 0 or self._bytes_done <= 0:
            return
        eta = elapsed / self._bytes_done * (self._total - self._bytes_done)
        invoke_callback(self._emit_eta, max(0.0, eta))


@dataclass
class MoveBatchResult:
    moved_any: bool = False
    ok_count: int = 0
    error_count: int = 0
    moved_log: list[tuple[str, str]] = field(default_factory=list)


class MoveBatchExecutor:
    """Execute the per-file move sequence with explicit injected boundaries."""

    def __init__(
        self,
        *,
        files: list[tuple[str, int]],
        router,
        journal,
        completion: MoveCompletionService,
        companion_resume_sources: dict[str, str],
        wait: Callable[[], None],
        abort_type: Callable[[], str | None],
        prepare_move: Callable[..., dict] | None = None,
        stage_sidecars: Callable[..., dict] | None = None,
        rollback_staged_sidecars: Callable[[dict | None], None] | None = None,
        move: MoveFn,
        get_last_move_result: Callable[[], dict],
        set_last_move_result: Callable[[dict], None],
        append_move_report: Callable[[dict | None], None],
        log: LogFn,
        progress_hook: Callable[[int], None],
        file_counted: Callable[[int, int], None],
        diagnostic_target_for: Callable[[str], object] | None = None,
        diagnostic_sidecars_for: Callable[[str], Iterable[str]] | None = None,
    ) -> None:
        self._files = files
        self._router = router
        self._journal = journal
        self._completion = completion
        self._companion_resume_sources = companion_resume_sources
        self._wait = wait
        self._abort_type = abort_type
        self._prepare_move = prepare_move or self._default_prepare_move
        self._stage_sidecars = stage_sidecars or self._default_stage_sidecars
        self._rollback_staged_sidecars = rollback_staged_sidecars or (lambda _stage: None)
        self._move = move
        self._get_last_move_result = get_last_move_result
        self._set_last_move_result = set_last_move_result
        self._append_move_report = append_move_report
        self._log = log
        self._progress_hook = progress_hook
        self._file_counted = file_counted
        self._diagnostic_target_for = diagnostic_target_for or (lambda _path: None)
        self._diagnostic_sidecars_for = diagnostic_sidecars_for or (lambda _path: ())
        self.result = MoveBatchResult()

    @staticmethod
    def _default_prepare_move(path: str, target: str) -> dict:
        dest = str(Path(target) / Path(path).name)
        return {
            "ready": True,
            "dest_path": dest,
            "result": {
                "kind": "video",
                "source_path": str(path),
                "target_dir": str(target),
                "dest_path": dest,
                "ok": False,
            },
        }

    @staticmethod
    def _default_stage_sidecars(
        _path: str, _target: str, _dest_path: str, _original_source: str
    ) -> dict:
        return {"ok": True, "protected_paths": [], "staged_paths": []}

    def _is_immediate_abort(self) -> bool:
        return self._abort_type() == "sofort"

    def _mark_file_error(self, path: str, journal_message: str, log_prefix: str) -> None:
        self._log(f"{log_prefix}: {Path(path).name}", "warn")
        self._journal.finish_file(path, status="error", message=journal_message)

    def _finish_failed_move(self, path: str, move_result: dict) -> None:
        self._append_move_report(move_result)
        status = "skipped" if move_result.get("skipped_conflict") else "error"
        self._journal.finish_file(
            path,
            status=status,
            dest_path=str(move_result.get("dest_path") or ""),
            message="Zielkonflikt übersprungen" if status == "skipped" else "Verschieben fehlgeschlagen",
        )
        self._log(f"Fehler: {Path(path).name}", "error")

    def _log_unavailable_source(self, path: str, probe) -> None:
        parent_text = (
            "ja" if probe.parent_available is True
            else "nein" if probe.parent_available is False
            else "unbekannt"
        )
        planned = self._diagnostic_target_for(path)
        companion_status = probe_companions(self._diagnostic_sidecars_for(path))
        lines = [
            "⚠️ Move-Quelle auch nach Wiederholungsprüfung nicht erreichbar.",
            f"   Quelle: {path}",
            "   Quelle erreichbar: nein",
            f"   Prüfung: {probe.attempts} Versuch(e), letzter Fehler: {probe.error_text or 'unbekannt'}",
            f"   Elternordner erreichbar: {parent_text}",
            f"   Dateigröße: {probe.size_bytes if probe.size_bytes is not None else 'unbekannt'}",
            f"   Geplantes Ziel: {planned if planned else 'nicht gesetzt'}",
            f"   Companion-Dateien: {len(companion_status)}",
        ]
        if probe.parent_error_text:
            lines.append(f"   Elternordner-Fehler: {probe.parent_error_text}")
        for companion, available, error in companion_status:
            marker = "✅" if available else "⚠️"
            suffix = "" if available else f" ({error})"
            lines.append(f"      {marker} {companion}{suffix}")
        self._log("\n".join(lines), "warn")

    def run(self) -> MoveBatchResult:
        result = self.result
        files_done = 0
        total_files = len(self._files)

        for path, _size in self._files:
            self._wait()
            if self._is_immediate_abort():
                break

            source_probe = probe_move_source(path)
            if not source_probe.available:
                self._log_unavailable_source(path, source_probe)
                self._mark_file_error(path, "Quelldatei nicht erreichbar", "Nicht erreichbar")
                result.error_count += 1
                files_done += 1
                invoke_callback(self._file_counted, files_done, total_files)
                continue

            # Transaction boundary BEFORE resolving the destination.  Runtime
            # target edits are allowed only while the journal row is queued.
            # Marking the file running first makes target acceptance and target
            # consumption linearizable: either the edit wins before this point
            # and route() sees it, or the edit is rejected afterwards.
            self._journal.start_file(path)

            target = self._router.route(path)
            if not target:
                self._mark_file_error(path, "Kein gültiges Verschiebeziel ermittelt", "übersprungen")
                result.error_count += 1
                files_done += 1
                invoke_callback(self._file_counted, files_done, total_files)
                continue

            self._journal.set_destination(
                path,
                target_dir=str(target),
                dest_path=str(Path(target) / Path(path).name),
            )
            self._log(f"Move: {Path(path).name}\n   -> {str(target).replace('/', chr(92))}", "info")

            original_source = self._companion_resume_sources.get(path, path)
            staged_sidecars: dict | None = None
            if original_source != path:
                ok, move_result = self._completion.companion_resume_result(
                    video_path=path,
                    target_dir=str(target),
                    original_source=original_source,
                )
                self._set_last_move_result(move_result)
            else:
                prepared = self._prepare_move(path, target)
                move_result = dict(prepared.get("result") or {})
                self._set_last_move_result(move_result)
                if not bool(prepared.get("ready", True)):
                    files_done += 1
                    result.error_count += 1
                    self._finish_failed_move(path, move_result)
                    invoke_callback(self._file_counted, files_done, total_files)
                    if self._abort_type() == "nach_datei":
                        break
                    continue

                planned_dest = str(
                    prepared.get("dest_path")
                    or (Path(target) / Path(path).name)
                )
                self._journal.set_destination(
                    path, target_dir=str(target), dest_path=planned_dest
                )

                staged_sidecars = self._stage_sidecars(
                    path, str(target), planned_dest, original_source
                )
                if not bool(staged_sidecars.get("ok", True)):
                    self._rollback_staged_sidecars(staged_sidecars)
                    failed_count = int(staged_sidecars.get("failed", 0) or 0)
                    message = (
                        f"{failed_count} Companion-Datei(en) konnten vor dem Video-Commit "
                        "nicht bereitgestellt werden"
                    )
                    self._journal.finish_file(
                        path,
                        status="error",
                        dest_path=planned_dest,
                        message=message,
                        phase="video_pending",
                    )
                    self._log(f"⚠️ {message}: {Path(path).name}", "warn")
                    files_done += 1
                    result.error_count += 1
                    invoke_callback(self._file_counted, files_done, total_files)
                    if self._abort_type() == "nach_datei":
                        break
                    continue

                ok = self._move(
                    path,
                    target,
                    hook=self._progress_hook,
                    prepared=prepared,
                    protected_paths=staged_sidecars.get("protected_paths") or [],
                )
                move_result = dict(self._get_last_move_result() or {})
                if not ok:
                    self._rollback_staged_sidecars(staged_sidecars)

            files_done += 1
            if ok:
                result.moved_any = True
                result.moved_log.append((Path(path).name, str(target)))
                outcome = self._completion.complete(
                    journal_source=path,
                    sidecar_key=path,
                    target_dir=str(target),
                    original_source=original_source,
                    move_result=move_result,
                    staged_sidecar_paths=(
                        staged_sidecars.get("staged_paths")
                        if staged_sidecars is not None
                        else None
                    ),
                )
                if outcome.error:
                    result.error_count += 1
                else:
                    result.ok_count += 1
            else:
                move_result = dict(self._get_last_move_result() or {})
                if self._is_immediate_abort():
                    break
                result.error_count += 1
                self._finish_failed_move(path, move_result)

            invoke_callback(self._file_counted, files_done, total_files)
            if self._abort_type() == "nach_datei":
                break

        return result
