# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from ..core.sidecar_journal import SidecarJournal
from ..core.sidecar_transaction import SidecarCommitError, SidecarCommitTransaction
from .workflow_postprocess_commit import WorkflowPostprocessCommitService
from .workflow_sidecar_commit import WorkflowSidecarCommitService


class WorkflowOutputCommitCoordinator:
    """Orchestrates verified video replace, sidecars and optional postprocessing."""

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
        abort_check=None,
    ) -> None:
        self._replace_service = replace_service
        self._logger = logger
        self._sidecars = WorkflowSidecarCommitService(
            logger=logger,
            sidecar_outputs=sidecar_outputs,
        )
        self._abort_check = abort_check
        self._postprocess = WorkflowPostprocessCommitService(
            logger=logger,
            result_service=result_service,
            sidecar_outputs=sidecar_outputs,
            postprocess_outputs=postprocess_outputs,
            service=postprocess_service,
            coordinator=postprocess_coordinator,
        )

    def replace(self, ctx) -> None:
        # Source-based trickplay must be rendered before destructive overwrite.
        # It targets the final video stem directly; because it is rendered from
        # the still-intact original it remains valid even if the video replace
        # later fails.
        self._postprocess.prepare_source_trickplay(
            ctx, final_output=self._anticipated_final_output(ctx)
        )
        staged_sidecars = list(ctx.sidecar_paths or [])
        sidecar_tx = None
        try:
            self._raise_if_aborted("nach Source-Trickplay")
            if staged_sidecars and ctx.output_path:
                sidecar_tx = self._commit_sidecars(
                    ctx,
                    final_output=self._anticipated_final_output(ctx),
                    store_result=False,
                )
        except Exception:
            self._postprocess.discard_prepared_source_trickplay(ctx, cleanup=False)
            raise

        try:
            self._raise_if_aborted("vor dem Video-Replace")
            ctx.final_output_path = self._replace_service.replace(
                input_path=ctx.input_path,
                output_path=ctx.output_path,
                container=ctx.container,
            )
        except Exception:
            if sidecar_tx is not None:
                self._rollback_sidecars(sidecar_tx, ctx, staged_sidecars)
            self._postprocess.discard_prepared_source_trickplay(ctx, cleanup=False)
            raise

        self._apply_replace_state(ctx)
        if getattr(ctx, "replacement_blocked", False):
            if sidecar_tx is not None:
                self._rollback_sidecars(sidecar_tx, ctx, staged_sidecars)
            self._postprocess.discard_prepared_source_trickplay(ctx, cleanup=False)
            self.finalize_sidecars(ctx)
            return

        if sidecar_tx is not None:
            self._store_sidecar_commit(ctx, sidecar_tx, staged_sidecars)
            self._finish_sidecar_journal(sidecar_tx)
        else:
            self.finalize_sidecars(ctx)
        if getattr(ctx, "cleanup_pending", False):
            # No Future may announce success for a video with an open commit.
            # Optional companions still run, without owning the terminal result.
            self._run_postprocess(ctx)
            ctx.postprocess_pending = False
        else:
            ctx.postprocess_pending = self.start_postprocess(ctx)

    def _raise_if_aborted(self, stage: str) -> None:
        check = self._abort_check
        if callable(check) and bool(check()):
            raise RuntimeError(f"Sofort-Abbruch {stage}; destruktiver Commit wurde nicht gestartet.")

    def _apply_replace_state(self, ctx) -> None:
        cleanup_pending = getattr(self._replace_service, "cleanup_pending", lambda _path: False)
        if cleanup_pending(ctx.input_path):
            ctx.cleanup_pending = True
            ctx.cleanup_pending_message = str(
                getattr(self._replace_service, "last_cleanup_message", "")
                or "Ziel ist installiert, Cleanup des Originals/Backups steht noch aus."
            )
        was_blocked = getattr(self._replace_service, "was_blocked", lambda _path: False)
        if not was_blocked(ctx.input_path):
            return
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

    @staticmethod
    def _anticipated_final_output(ctx) -> str:
        if getattr(ctx, "replace_original", False):
            return str(Path(ctx.input_path).with_suffix(f".{ctx.container}"))
        return str(ctx.output_path)

    # Compatibility delegates used by tests/extensions.
    def _commit_sidecars(self, ctx, **kwargs):
        return self._sidecars.commit(ctx, **kwargs)

    def _store_sidecar_commit(self, ctx, tx, source_paths) -> None:
        self._sidecars.store(ctx, tx, source_paths)

    def _rollback_sidecars(self, tx, ctx, source_paths) -> None:
        self._sidecars.rollback(tx, ctx, source_paths)

    def _finish_sidecar_journal(self, tx) -> None:
        self._sidecars.finish_journal(tx)

    def finalize_sidecars(self, ctx) -> None:
        self._sidecars.finalize(ctx)

    def _run_postprocess(self, ctx) -> None:
        self._postprocess.run_sync(ctx)

    def start_postprocess(self, ctx) -> bool:
        return self._postprocess.start(ctx)
