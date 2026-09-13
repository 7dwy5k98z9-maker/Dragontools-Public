# -*- coding: utf-8 -*-
"""Single-file transaction for the Dolby Vision remux worker."""
from __future__ import annotations

import time
import traceback
from pathlib import Path

from ..core.media_analyzer import analyze_media
from ..core.sidecar_journal import SidecarJournal
from ..core.sidecar_transaction import SidecarCommitError, SidecarCommitTransaction
from ..rules.subtitle_rules import any_sidecar_export_enabled
from .converter_utils import _fd, _fs
from .worker_events import progress_event, result_event


class DVRemuxJobRunner:
    """Own the complete transaction for one input file.

    The QThread remains responsible for queue/control/lifecycle only.  This
    class owns media analysis, remux execution, sidecar commit/rollback and
    final result signaling.
    """

    def __init__(
        self,
        worker,
        *,
        process_runner,
        pipeline,
        output_manager,
        subtitle_service,
        prepare_metadata=None,
        emit_success=None,
    ):
        self.worker = worker
        self.process_runner = process_runner
        self.pipeline = pipeline
        self.output_manager = output_manager
        self.subtitle_service = subtitle_service
        self.prepare_metadata = prepare_metadata
        self.emit_success = emit_success

    def run(self, input_path: str) -> bool:
        output_path: str | None = None
        remux_complete = False
        try:
            self._emit_started(input_path)
            if self.prepare_metadata is not None:
                name, media_info, dur_ms, file_override = self.prepare_metadata(input_path)
            else:
                name, media_info, dur_ms, file_override = self._prepare_metadata(input_path)
            self.worker.log(f"DV-Remux: {name}", "info")

            output_path = self.output_manager.build_output_path(input_path)
            size_before = Path(input_path).stat().st_size if Path(input_path).exists() else 0
            start_ts = time.time()

            if not self.pipeline.run(
                input_path=input_path,
                output_path=output_path,
                mi=media_info,
                dur_ms=dur_ms,
                file_override=file_override,
                name=name,
            ) or self.worker.abort_requested:
                if not self.worker.abort_requested:
                    self.worker.log(f"Remux fehlgeschlagen: {name}", "error")
                self._emit_failed(input_path)
                return False

            staged_sidecars = self._export_sidecars_if_needed(
                input_path=input_path,
                output_path=output_path,
                media_info=media_info,
                file_override=file_override,
            )
            if staged_sidecars is None:
                return False

            sidecar_tx = self._commit_sidecars(input_path, output_path, staged_sidecars)
            if staged_sidecars and sidecar_tx is None:
                return False

            replace_ok, output_path = self.output_manager.replace_output_if_needed(
                input_path,
                output_path,
            )
            if not replace_ok or self.worker.abort_requested:
                self._rollback_sidecars(sidecar_tx, staged_sidecars)
                self._emit_failed(input_path)
                return False

            self._finalize_sidecars(input_path, sidecar_tx)
            if self.emit_success is not None:
                self.emit_success(input_path, output_path, name, size_before, start_ts)
            else:
                self._emit_success(input_path, output_path, name, size_before, start_ts)
            remux_complete = True
            return True
        except Exception:
            self.worker.log(
                f"Unbehandelte Ausnahme in DVRemuxJobRunner bei {Path(input_path).name}",
                "error",
            )
            self.worker.log(traceback.format_exc(), "error")
            self._emit_failed(input_path)
            return False
        finally:
            if not remux_complete:
                self.output_manager.cleanup_incomplete(input_path, output_path)

    def _prepare_metadata(self, input_path: str):
        name = Path(input_path).name
        media_info = analyze_media(input_path, self.worker.tools)
        for warning in getattr(media_info, "analysis_warnings", []) or []:
            self.worker.log(f"Analyse-Warnung: {warning}", "warn")
        dur_ms = self.process_runner.probe_ms(input_path)
        file_override = self.worker.file_overrides.get(input_path)
        return name, media_info, dur_ms, file_override

    def _export_sidecars_if_needed(
        self,
        *,
        input_path: str,
        output_path: str,
        media_info,
        file_override: dict | None,
    ) -> list[str] | None:
        w = self.worker
        if any_sidecar_export_enabled(w.subtitle_rules, container=w.container):
            export_result = self.subtitle_service.export_sidecars_result(
                input_path=input_path,
                output_base=Path(output_path).with_suffix(""),
                media_info=media_info,
                file_override=file_override,
                abort_check=lambda: w.abort_requested,
                preserve_burn_candidate=True,
                container=w.container,
            )
            staged = list(export_result.exported_paths)
            if export_result.complete:
                return staged
            self.cleanup_generated_sidecars(staged)
            w.log(
                export_result.failure_summary() or "Sidecar-Export unvollständig.",
                "error",
            )
            self._emit_failed(input_path)
            return None

        if getattr(media_info, "subtitle_streams", None):
            w.log(
                "  💬 MKV-Ziel: ausgewählte Untertitel sind im Container gespeichert; "
                "kein externer Sidecar-Export.",
                "info",
            )
        return []

    def _commit_sidecars(
        self,
        input_path: str,
        output_path: str,
        staged_sidecars: list[str],
    ) -> SidecarCommitTransaction | None:
        if not staged_sidecars:
            return None

        anticipated_output = (
            str(Path(input_path).with_suffix(f".{self.worker.container}"))
            if self.worker.overwrite_original
            else output_path
        )
        try:
            transaction = SidecarCommitTransaction(
                staged_sidecars,
                source_base=Path(output_path).with_suffix(""),
                destination_base=Path(anticipated_output).with_suffix(""),
            )
            journal = SidecarJournal.start(
                video_staging=output_path,
                video_destination=anticipated_output,
                records=transaction.prepare_records(),
                video_committed=(str(Path(output_path)) == str(Path(anticipated_output))),
            )
            setattr(transaction, "_dragontools_journal", journal)
            transaction.commit()
            journal.set_status("sidecars_committed")
            return transaction
        except SidecarCommitError as exc:
            self.cleanup_generated_sidecars(staged_sidecars)
            self.worker.log(f"Sidecar-Finalisierung fehlgeschlagen: {exc}", "error")
            self._emit_failed(input_path)
            return None

    def _rollback_sidecars(
        self,
        transaction: SidecarCommitTransaction | None,
        staged_sidecars: list[str],
    ) -> None:
        if transaction is not None:
            try:
                transaction.rollback()
                journal = getattr(transaction, "_dragontools_journal", None)
                if journal is not None:
                    journal.finish()
            except SidecarCommitError as exc:
                self.worker.log(f"Sidecar-Rollback unvollständig: {exc}", "error")
        self.cleanup_generated_sidecars(staged_sidecars)

    def _finalize_sidecars(
        self,
        input_path: str,
        transaction: SidecarCommitTransaction | None,
    ) -> None:
        paths = list(transaction.final_paths) if transaction is not None else []
        self.worker._sidecar_outputs[input_path] = paths
        if transaction is None:
            return

        for destination, backup in transaction.backup_pairs:
            self.worker.log(
                "Vorhandenes Sidecar wurde nicht gelöscht, sondern gesichert: "
                f"{destination.name} -> {backup.name}",
                "warn",
            )
        journal = getattr(transaction, "_dragontools_journal", None)
        if journal is not None:
            journal.finish()

    def _emit_started(self, input_path: str) -> None:
        self.worker.event.emit(result_event(input_path, input_path, "⏳"))
        self.worker.file_result.emit(input_path, input_path, "⏳")
        self.worker.event.emit(progress_event(input_path, 0, None))
        self.worker.file_progress.emit(input_path, 0, None)

    def _emit_failed(self, input_path: str) -> None:
        self.worker.event.emit(result_event(input_path, input_path, "❌"))
        self.worker.file_result.emit(input_path, input_path, "❌")

    def _emit_success(
        self,
        input_path: str,
        output_path: str,
        name: str,
        size_before: int,
        start_ts: float,
    ) -> None:
        size_after = Path(output_path).stat().st_size if Path(output_path).exists() else 0
        duration = time.time() - start_ts
        self.worker.log(
            f"✅ {name} → {Path(output_path).name} | "
            f"{_fs(size_before)} → {_fs(size_after)} | {_fd(duration)}",
            "success",
        )
        self.worker.file_progress.emit(input_path, 100, None)
        self.worker.event.emit(progress_event(input_path, 100, None))
        self.worker.event.emit(result_event(input_path, output_path, "✅"))
        self.worker.file_result.emit(input_path, output_path, "✅")

    @staticmethod
    def cleanup_generated_sidecars(paths: list[str] | tuple[str, ...]) -> None:
        for raw in paths:
            path = Path(raw)
            try:
                if path.exists() or path.is_symlink():
                    path.unlink()
            except OSError:
                pass
