# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from ..core.sidecar_transaction import SidecarCommitError, SidecarCommitTransaction
from ..core.sidecar_journal import SidecarJournal


class WorkflowOutputCommitCoordinator:
    """Commit-Grenze fuer Video, Sidecars und nachgelagertes Postprocessing."""

    def __init__(
        self,
        *,
        replace_service,
        logger,
        result_service,
        sidecar_outputs: dict[str, list[str]] | None,
        postprocess_outputs: dict[str, list[dict]] | None,
        postprocess_service=None,
        postprocess_coordinator=None,
    ) -> None:
        self._replace_service = replace_service
        self._logger = logger
        self._result_service = result_service
        self._sidecar_outputs = sidecar_outputs
        self._postprocess_outputs = postprocess_outputs
        self._postprocess_service = postprocess_service
        self._postprocess_coordinator = postprocess_coordinator
        self._sidecar_journals: dict[int, SidecarJournal] = {}

    def replace(self, ctx) -> None:
        staged_sidecars = list(ctx.sidecar_paths or [])
        sidecar_tx: SidecarCommitTransaction | None = None

        # Sidecars werden vor dem destruktiven Video-Replace auf den erwarteten
        # finalen Stem committed. Schlaegt das Video-Replace im laufenden
        # Prozess fehl, werden die Sidecars auf ihre Staging-Pfade zurueckgerollt.
        if staged_sidecars and ctx.output_path:
            sidecar_tx = self._commit_sidecars(
                ctx,
                final_output=self._anticipated_final_output(ctx),
                store_result=False,
            )

        try:
            ctx.final_output_path = self._replace_service.replace(
                input_path=ctx.input_path,
                output_path=ctx.output_path,
                container=ctx.container,
            )
        except Exception:
            if sidecar_tx is not None:
                self._rollback_sidecars(sidecar_tx, ctx, staged_sidecars)
            raise

        cleanup_pending = getattr(
            self._replace_service, "cleanup_pending", lambda _path: False
        )
        if cleanup_pending(ctx.input_path):
            ctx.cleanup_pending = True
            ctx.cleanup_pending_message = str(
                getattr(self._replace_service, "last_cleanup_message", "")
                or "Ziel ist installiert, Cleanup des Originals/Backups steht noch aus."
            )

        was_blocked = getattr(self._replace_service, "was_blocked", lambda _path: False)
        if was_blocked(ctx.input_path):
            ctx.replacement_blocked = True
            ctx.replacement_block_reason = (
                getattr(self._replace_service, "last_block_reason", "")
                or "Ausgabedatei verletzt die Groessenregel; Original wurde nicht ersetzt."
            )
            ctx.replacement_archived_path = (
                getattr(self._replace_service, "last_preserved_path", None)
                or ctx.final_output_path
            )
            ctx.keep_failed_output = True

            if sidecar_tx is not None:
                self._rollback_sidecars(sidecar_tx, ctx, staged_sidecars)
                sidecar_tx = None
            self.finalize_sidecars(ctx)
        elif sidecar_tx is not None:
            self._store_sidecar_commit(ctx, sidecar_tx, staged_sidecars)
            self._finish_sidecar_journal(sidecar_tx)
        else:
            self.finalize_sidecars(ctx)

        if not getattr(ctx, "replacement_blocked", False):
            ctx.postprocess_pending = self.start_postprocess(ctx)

    @staticmethod
    def _anticipated_final_output(ctx) -> str:
        if getattr(ctx, "replace_original", False):
            return str(Path(ctx.input_path).with_suffix(f".{ctx.container}"))
        return str(ctx.output_path)

    def _commit_sidecars(
        self,
        ctx,
        *,
        final_output: str,
        store_result: bool,
        video_committed: bool = False,
    ) -> SidecarCommitTransaction:
        sidecars = list(ctx.sidecar_paths or [])
        if not sidecars or not ctx.output_path:
            raise ValueError("Sidecar-Commit ohne Sidecar- oder Output-Pfad aufgerufen.")

        tx = SidecarCommitTransaction(
            sidecars,
            source_base=Path(ctx.output_path).with_suffix(""),
            destination_base=Path(final_output).with_suffix(""),
        )
        # Der vollstaendige Plan wird vor der ersten Mutation dauerhaft gespeichert.
        records = tx.prepare_records()
        journal = SidecarJournal.start(
            video_staging=str(ctx.output_path),
            video_destination=str(final_output),
            records=records,
            video_committed=video_committed,
        )
        self._sidecar_journals[id(tx)] = journal
        try:
            tx.commit()
            journal.set_status("sidecars_committed", fatal=False)
        except Exception as exc:
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
            else:
                journal.finish()
                self._sidecar_journals.pop(id(tx), None)
            if isinstance(exc, SidecarCommitError):
                raise RuntimeError(f"Sidecar-Finalisierung fehlgeschlagen: {exc}") from exc
            raise

        if store_result:
            self._store_sidecar_commit(ctx, tx, sidecars)
            if video_committed:
                self._finish_sidecar_journal(tx)
        return tx

    def _store_sidecar_commit(
        self,
        ctx,
        tx: SidecarCommitTransaction,
        source_paths: list[str],
    ) -> None:
        finalized = list(tx.final_paths)
        for source, destination in zip(source_paths, finalized):
            if Path(source) != Path(destination):
                self._logger.info(
                    f"Sidecar verschoben: {Path(source).name} -> {Path(destination).name}"
                )
        for destination, backup in tx.backup_pairs:
            self._logger.warn(
                "Vorhandenes Sidecar wurde nicht geloescht, sondern gesichert: "
                f"{destination.name} -> {backup.name}"
            )
        ctx.sidecar_paths = finalized
        if self._sidecar_outputs is not None:
            self._sidecar_outputs[ctx.input_path] = finalized

    def _rollback_sidecars(
        self,
        tx: SidecarCommitTransaction,
        ctx,
        source_paths: list[str],
    ) -> None:
        try:
            tx.rollback()
        except SidecarCommitError as exc:
            self._logger.error(f"Sidecar-Rollback unvollstaendig: {exc}")
            raise RuntimeError(f"Sidecar-Rollback unvollstaendig: {exc}") from exc
        ctx.sidecar_paths = list(source_paths)
        self._finish_sidecar_journal(tx)

    def _finish_sidecar_journal(self, tx: SidecarCommitTransaction) -> None:
        journal = self._sidecar_journals.pop(id(tx), None)
        if journal is not None:
            journal.finish()

    def finalize_sidecars(self, ctx) -> None:
        sidecars = list(ctx.sidecar_paths or [])
        if not sidecars:
            if self._sidecar_outputs is not None:
                self._sidecar_outputs[ctx.input_path] = []
            return

        final_output = ctx.final_output_path or ctx.output_path
        if not (ctx.output_path and final_output):
            raise RuntimeError("Sidecars vorhanden, aber finaler Output-Pfad fehlt.")

        tx = self._commit_sidecars(
            ctx,
            final_output=str(final_output),
            store_result=False,
            video_committed=True,
        )
        self._store_sidecar_commit(ctx, tx, sidecars)
        self._finish_sidecar_journal(tx)

    def _run_postprocess(self, ctx) -> None:
        service = self._postprocess_service
        if service is None:
            return
        final_output = ctx.final_output_path or ctx.output_path
        if not final_output:
            return
        try:
            created = service.run(input_path=ctx.input_path, output_path=final_output)
        except Exception as exc:
            self._logger.warn(f"Post-Processing uebersprungen: {exc}")
            if self._postprocess_outputs is not None:
                self._postprocess_outputs[ctx.input_path] = [
                    {
                        "kind": "postprocess",
                        "status": "error",
                        "path": "",
                        "message": str(exc),
                    }
                ]
            return
        details = list(getattr(service, "last_items", []) or [])
        if self._postprocess_outputs is not None:
            self._postprocess_outputs[ctx.input_path] = [dict(item) for item in details]
        if not created:
            return
        sidecars = list(ctx.sidecar_paths or [])
        for path in created:
            if path not in sidecars:
                sidecars.append(path)
        ctx.sidecar_paths = sidecars
        if self._sidecar_outputs is not None:
            self._sidecar_outputs[ctx.input_path] = sidecars

    def start_postprocess(self, ctx) -> bool:
        service = self._postprocess_service
        if service is None:
            return False
        final_output = ctx.final_output_path or ctx.output_path
        if not final_output:
            return False
        try:
            is_enabled = getattr(service, "is_enabled", None)
            if callable(is_enabled) and not is_enabled():
                return False
        except Exception as exc:
            self._logger.warn(
                f"Post-Processing deaktiviert: Statuspruefung fehlgeschlagen: {exc}"
            )
            return False

        coordinator = self._postprocess_coordinator
        if coordinator is None:
            self._run_postprocess(ctx)
            return False

        sidecars = list(ctx.sidecar_paths or [])
        if self._sidecar_outputs is not None:
            self._sidecar_outputs[ctx.input_path] = sidecars
        try:
            return bool(
                coordinator.submit(
                    input_path=ctx.input_path,
                    output_path=final_output,
                    existing_sidecars=sidecars,
                    sidecar_outputs=self._sidecar_outputs,
                    postprocess_outputs=self._postprocess_outputs,
                    result_service=self._result_service,
                )
            )
        except Exception as exc:
            self._logger.warn(
                f"Post-Processing konnte nicht im Hintergrund starten: {exc}"
            )
            self._run_postprocess(ctx)
            return False
