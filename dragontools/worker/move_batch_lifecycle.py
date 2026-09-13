# -*- coding: utf-8 -*-
"""Journal-, Batch- und Shutdown-Lifecycle für ``MoveThread``."""
from __future__ import annotations

from ..core.move_journal import MoveJournal, MoveJournalWriteError, archive_move_journal_path
from ..core.system_shutdown import schedule_system_shutdown
from .move_batch_executor import MoveBatchExecutor, MoveProgressTracker
from .move_completion_service import MoveCompletionService


class MoveBatchLifecycleMixin:
    """Kapselt Run-übergreifenden Journal- und Batch-Lifecycle."""

    def _start_move_journal(self, files: list[tuple[str, int]]) -> None:
        self._move_journal = MoveJournal.start(
            files=[path for path, _size in files],
            target_paths={
                "tv": str(self.tv_path or ""),
                "anime": str(self.anime_path or ""),
                "film": str(self.filme_path or ""),
            },
            planned_targets=dict(self.planned_targets),
            sidecar_outputs_by_video=dict(self._sidecar_outputs_by_video),
            conflict_mode=self.conflict_mode,
            log_file=self.log_file_path,
            root=self._move_journal_root,
            on_write_error=lambda msg: self._log(
                f"❌ {msg} – Verschieben wird aus Sicherheitsgründen abgebrochen.", "error"
            ),
        )
        self._archive_superseded_journal()

    def _execute_move_batch(self, files: list[tuple[str, int]], total_bytes: int):
        progress = MoveProgressTracker(
            total_bytes,
            emit_progress=self.progress.emit,
            emit_eta=self.move_eta.emit,
        )
        executor = MoveBatchExecutor(
            files=files,
            router=self._router(),
            journal=self._move_journal,
            completion=self._completion_service(),
            companion_resume_sources=dict(self._companion_resume_sources),
            wait=self._wait,
            abort_type=lambda: self.abort_type if self.abort_requested else None,
            move=self._move,
            get_last_move_result=lambda: dict(getattr(self, "_last_move_result", None) or {}),
            set_last_move_result=lambda result: setattr(self, "_last_move_result", result),
            append_move_report=self._append_move_report,
            log=self._log,
            progress_hook=progress.update,
            file_counted=self.file_counted.emit,
        )
        try:
            return executor.run()
        finally:
            # Teilresultate bleiben auch bei einer unerwarteten Ausnahme sichtbar.
            self.ok_count = executor.result.ok_count
            self.error_count = executor.result.error_count
            self._moved_log = list(executor.result.moved_log)

    def _archive_superseded_journal(self) -> None:
        if not self._supersedes_journal_path:
            return
        try:
            archive_move_journal_path(self._supersedes_journal_path, status="restored_to_retry")
            self._supersedes_journal_path = ""
        except OSError as exc:
            self._log(
                f"⚠️ Altes Move-Journal konnte nach Start des Retry-Laufs nicht archiviert werden: {exc}",
                "warn",
            )

    def _handle_optional_shutdown(self) -> bool:
        wants_shutdown = self._shutdown_getter() if self._shutdown_getter is not None else self.shutdown_after
        if not wants_shutdown:
            return False
        resp = self._ask({"type": "confirm_shutdown_with_countdown", "seconds": 30})
        if resp.get("ok"):
            return schedule_system_shutdown(delay_seconds=5, log=self._log)
        self.user_declined_shutdown = True
        return False

    def _finalize_journal(self) -> bool:
        if self._move_journal is None:
            return True
        try:
            keep_active = self._move_journal.has_retryable_files()
            if self.abort_requested:
                status = "aborted"
            elif keep_active:
                status = "incomplete"
            else:
                status = "completed"
            self._move_journal.finish_run(status=status, keep_active=keep_active)
            return True
        except (OSError, ValueError, TypeError, MoveJournalWriteError) as exc:
            # Der Dateitransfer kann bereits erfolgreich sein, der Run ist ohne
            # ein sauber persistiertes/archiviertes Journal aber nicht vollständig
            # abgeschlossen. Als echter Move-Fehler mitzählen, damit GUI und
            # Abschlussbericht keinen reinen Erfolgszustand anzeigen.
            self.error_count += 1
            self.journal_finalize_failed = True
            self._log(f"❌ Move-Journal konnte nicht finalisiert werden: {exc}", "error")
            return False
