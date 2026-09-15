# -*- coding: utf-8 -*-
"""Transactional sidecar commit/rollback service for converter outputs."""
from __future__ import annotations

from pathlib import Path

from ..core.sidecar_journal import SidecarJournal
from ..core.sidecar_transaction import SidecarCommitError, SidecarCommitTransaction


class WorkflowSidecarCommitService:
    def __init__(self, *, logger, sidecar_outputs: dict[str, list[str]] | None) -> None:
        self._logger = logger
        self._sidecar_outputs = sidecar_outputs
        self._journals: dict[int, SidecarJournal] = {}

    def commit(self, ctx, *, final_output: str, store_result: bool, video_committed: bool = False) -> SidecarCommitTransaction:
        sidecars = list(ctx.sidecar_paths or [])
        if not sidecars or not ctx.output_path:
            raise ValueError("Sidecar-Commit ohne Sidecar- oder Output-Pfad aufgerufen.")
        tx = SidecarCommitTransaction(
            sidecars,
            source_base=Path(ctx.output_path).with_suffix(""),
            destination_base=Path(final_output).with_suffix(""),
        )
        journal = SidecarJournal.start(
            video_staging=str(ctx.output_path),
            video_destination=str(final_output),
            records=tx.prepare_records(),
            video_committed=video_committed,
        )
        self._journals[id(tx)] = journal
        try:
            tx.commit()
            journal.set_status("sidecars_committed", fatal=False)
        except Exception as exc:
            self._rollback_failed_commit(tx, journal, exc)
        if store_result:
            self.store(ctx, tx, sidecars)
            if video_committed:
                self.finish_journal(tx)
        return tx

    def _rollback_failed_commit(self, tx, journal, exc) -> None:
        try:
            tx.rollback()
        except Exception as rollback_exc:
            self._logger.error(
                "Sidecar-Commit und anschließender Rollback sind fehlgeschlagen; "
                f"Recovery-Journal bleibt erhalten: commit={exc}; rollback={rollback_exc}"
            )
            raise RuntimeError(
                "Sidecar-Finalisierung fehlgeschlagen und Rollback war unvollständig: "
                f"{rollback_exc}"
            ) from exc
        journal.finish()
        self._journals.pop(id(tx), None)
        if isinstance(exc, SidecarCommitError):
            raise RuntimeError(f"Sidecar-Finalisierung fehlgeschlagen: {exc}") from exc
        raise exc

    def store(self, ctx, tx: SidecarCommitTransaction, source_paths: list[str]) -> None:
        finalized = list(tx.final_paths)
        for source, destination in zip(source_paths, finalized):
            if Path(source) != Path(destination):
                self._logger.info(f"Sidecar verschoben: {Path(source).name} -> {Path(destination).name}")
        for destination, backup in tx.backup_pairs:
            self._logger.warn(
                "Vorhandenes Sidecar wurde nicht geloescht, sondern gesichert: "
                f"{destination.name} -> {backup.name}"
            )
        ctx.sidecar_paths = finalized
        if self._sidecar_outputs is not None:
            self._sidecar_outputs[ctx.input_path] = finalized

    def rollback(self, tx: SidecarCommitTransaction, ctx, source_paths: list[str]) -> None:
        try:
            tx.rollback()
        except SidecarCommitError as exc:
            self._logger.error(f"Sidecar-Rollback unvollstaendig: {exc}")
            raise RuntimeError(f"Sidecar-Rollback unvollstaendig: {exc}") from exc
        ctx.sidecar_paths = list(source_paths)
        self.finish_journal(tx)

    def finish_journal(self, tx: SidecarCommitTransaction) -> None:
        journal = self._journals.pop(id(tx), None)
        if journal is not None:
            journal.finish()

    def finalize(self, ctx) -> None:
        sidecars = list(ctx.sidecar_paths or [])
        if not sidecars:
            if self._sidecar_outputs is not None:
                self._sidecar_outputs[ctx.input_path] = []
            return
        final_output = ctx.final_output_path or ctx.output_path
        if not (ctx.output_path and final_output):
            raise RuntimeError("Sidecars vorhanden, aber finaler Output-Pfad fehlt.")
        tx = self.commit(ctx, final_output=str(final_output), store_result=False, video_committed=True)
        self.store(ctx, tx, sidecars)
        self.finish_journal(tx)
