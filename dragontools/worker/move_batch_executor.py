# -*- coding: utf-8 -*-
"""Batch execution for MoveThread without Qt/thread-state ownership."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

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
        self._emit_progress(min(int(self._bytes_done / self._total * 100), 99))
        elapsed = time.time() - self._started
        if elapsed <= 0 or self._bytes_done <= 0:
            return
        eta = elapsed / self._bytes_done * (self._total - self._bytes_done)
        self._emit_eta(max(0.0, eta))


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
        move: MoveFn,
        get_last_move_result: Callable[[], dict],
        set_last_move_result: Callable[[dict], None],
        append_move_report: Callable[[dict | None], None],
        log: LogFn,
        progress_hook: Callable[[int], None],
        file_counted: Callable[[int, int], None],
    ) -> None:
        self._files = files
        self._router = router
        self._journal = journal
        self._completion = completion
        self._companion_resume_sources = companion_resume_sources
        self._wait = wait
        self._abort_type = abort_type
        self._move = move
        self._get_last_move_result = get_last_move_result
        self._set_last_move_result = set_last_move_result
        self._append_move_report = append_move_report
        self._log = log
        self._progress_hook = progress_hook
        self._file_counted = file_counted
        self.result = MoveBatchResult()

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

    def run(self) -> MoveBatchResult:
        result = self.result
        files_done = 0
        total_files = len(self._files)

        for path, _size in self._files:
            self._wait()
            if self._is_immediate_abort():
                break

            if not Path(path).exists():
                self._mark_file_error(path, "Quelldatei nicht gefunden", "Nicht gefunden")
                result.error_count += 1
                files_done += 1
                self._file_counted(files_done, total_files)
                continue

            target = self._router.route(path)
            if not target:
                self._mark_file_error(path, "Kein gültiges Verschiebeziel ermittelt", "übersprungen")
                result.error_count += 1
                files_done += 1
                self._file_counted(files_done, total_files)
                continue

            self._log(f"Move: {Path(path).name}\n   -> {str(target).replace('/', chr(92))}", "info")
            self._journal.start_file(
                path,
                target_dir=str(target),
                dest_path=str(Path(target) / Path(path).name),
            )

            original_source = self._companion_resume_sources.get(path, path)
            if original_source != path:
                ok, move_result = self._completion.companion_resume_result(
                    video_path=path,
                    target_dir=str(target),
                    original_source=original_source,
                )
                self._set_last_move_result(move_result)
            else:
                ok = self._move(path, target, hook=self._progress_hook)
                move_result = dict(self._get_last_move_result() or {})

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

            self._file_counted(files_done, total_files)
            if self._abort_type() == "nach_datei":
                break

        return result
