# -*- coding: utf-8 -*-
"""Postprocessing dispatch/bookkeeping after a verified video commit."""
from __future__ import annotations


class WorkflowPostprocessCommitService:
    def __init__(self, *, logger, result_service, sidecar_outputs, postprocess_outputs, service=None, coordinator=None) -> None:
        self._logger = logger
        self._result_service = result_service
        self._sidecar_outputs = sidecar_outputs
        self._postprocess_outputs = postprocess_outputs
        self._service = service
        self._coordinator = coordinator

    def prepare_source_trickplay(self, ctx, *, final_output: str) -> None:
        service = self._service
        if service is None or not getattr(ctx, "replace_original", False) or not final_output:
            return
        prepare = getattr(service, "prepare_source_trickplay", None)
        if callable(prepare):
            ctx.prepared_source_trickplay = prepare(
                input_path=ctx.input_path, output_path=final_output
            )

    def discard_prepared_source_trickplay(self, ctx, *, cleanup: bool) -> None:
        ctx.prepared_source_trickplay = None

    def run_sync(self, ctx) -> None:
        service = self._service
        final_output = ctx.final_output_path or ctx.output_path
        if service is None or not final_output:
            return
        try:
            result = service.run_result(
                input_path=ctx.input_path,
                output_path=final_output,
                prepared_source_trickplay=getattr(ctx, "prepared_source_trickplay", None),
            )
            ctx.prepared_source_trickplay = None
            created = list(getattr(result, "created_paths", []) or [])
        except Exception as exc:
            self._logger.warn(f"Post-Processing uebersprungen: {exc}")
            if self._postprocess_outputs is not None:
                self._postprocess_outputs[ctx.input_path] = [{"kind": "postprocess", "status": "error", "path": "", "message": str(exc)}]
            return
        details = list(getattr(result, "items", []) or [])
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

    def start(self, ctx) -> bool:
        service = self._service
        final_output = ctx.final_output_path or ctx.output_path
        if service is None or not final_output:
            return False
        try:
            is_enabled = getattr(service, "is_enabled", None)
            if callable(is_enabled) and not is_enabled():
                return False
        except Exception as exc:
            self._logger.warn(f"Post-Processing deaktiviert: Statuspruefung fehlgeschlagen: {exc}")
            return False
        if self._coordinator is None:
            self.run_sync(ctx)
            return False
        sidecars = list(ctx.sidecar_paths or [])
        if self._sidecar_outputs is not None:
            self._sidecar_outputs[ctx.input_path] = sidecars
        try:
            submitted = bool(self._coordinator.submit(
                input_path=ctx.input_path,
                output_path=final_output,
                existing_sidecars=sidecars,
                sidecar_outputs=self._sidecar_outputs,
                postprocess_outputs=self._postprocess_outputs,
                result_service=self._result_service,
                prepared_source_trickplay=getattr(ctx, "prepared_source_trickplay", None),
            ))
            if submitted:
                ctx.prepared_source_trickplay = None
                # The coordinator emits 🧩 synchronously before registering its
                # completion callback, so WorkflowServices.finalize() must not
                # emit a second, potentially late pending result.
                ctx.postprocess_pending_announced = True
            return submitted
        except Exception as exc:
            self._logger.warn(f"Post-Processing konnte nicht im Hintergrund starten: {exc}")
            self.run_sync(ctx)
            return False
