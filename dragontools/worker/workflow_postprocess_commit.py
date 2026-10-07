# -*- coding: utf-8 -*-
"""Postprocessing dispatch/bookkeeping after a verified video commit."""
from __future__ import annotations

from concurrent.futures import Future
import threading


class WorkflowPostprocessCommitService:
    def __init__(self, *, logger, result_service, sidecar_outputs, postprocess_outputs, service=None, coordinator=None) -> None:
        self._logger = logger
        self._result_service = result_service
        self._sidecar_outputs = sidecar_outputs
        self._postprocess_outputs = postprocess_outputs
        self._service = service
        self._coordinator = coordinator

    def start_during_nfo(self, ctx, *, final_output: str) -> None:
        """Start lightweight NFO preparation without delaying the encode start."""
        service = self._service
        if service is None or not final_output or not getattr(ctx, "output_path", None):
            return
        enabled = getattr(service, "is_nfo_during_enabled", None)
        if callable(enabled) and not enabled():
            return
        prepare = getattr(service, "prepare_nfo_during_conversion", None)
        if not callable(prepare):
            return

        future: Future = Future()
        ctx.nfo_prepare_future = future

        def _run() -> None:
            try:
                result = prepare(
                    input_path=ctx.input_path,
                    output_path=ctx.output_path,
                    final_output_path=final_output,
                    media_info=getattr(ctx, "analysis", None),
                    media_contract=getattr(ctx, "expected_media_contract", None),
                )
            except BaseException as exc:  # Future boundary; propagated on await.
                future.set_exception(exc)
            else:
                future.set_result(result)

        threading.Thread(
            target=_run,
            name="DragonNfoPrepare",
            daemon=True,
        ).start()

    def await_prepared_nfo(self, ctx, *, refresh_technical: bool = True) -> None:
        future = getattr(ctx, "nfo_prepare_future", None)
        if future is None:
            return
        ctx.nfo_prepare_future = None
        try:
            prepared = future.result()
        except Exception as exc:
            self._logger.warn(f"NFO-Vorbereitung fehlgeschlagen: {exc}")
            prepared = None
        # The owned preparation must remain reachable if refresh/diagnostics
        # fail before returning a replacement result.
        ctx.prepared_nfo = prepared
        service = self._service
        refresh = getattr(service, "refresh_prepared_nfo", None) if service is not None else None
        if prepared is not None and callable(refresh) and refresh_technical:
            prepared = refresh(
                prepared,
                media_info=getattr(ctx, "analysis", None),
                media_contract=getattr(ctx, "expected_media_contract", None),
                video_path=getattr(ctx, "output_path", None),
            )
        ctx.prepared_nfo = prepared

    def commit_prepared_nfo(self, ctx, *, final_output: str) -> None:
        prepared = getattr(ctx, "prepared_nfo", None)
        if prepared is None:
            return
        ctx.prepared_nfo = None
        service = self._service
        commit = getattr(service, "commit_prepared_nfo", None) if service is not None else None
        if not callable(commit):
            return
        try:
            result = commit(prepared, final_output_path=final_output)
        except Exception as exc:
            self._logger.warn(f"Vorbereitete NFO konnte nicht übernommen werden: {exc}")
            self._merge_postprocess_items(ctx.input_path, [{
                "kind": "nfo", "status": "error", "path": "", "message": str(exc),
            }])
            return
        details = [dict(item) for item in (getattr(result, "items", []) or [])]
        self._merge_postprocess_items(ctx.input_path, details)
        created = [str(path) for path in (getattr(result, "created_paths", []) or []) if path]
        if created:
            sidecars = list(ctx.sidecar_paths or [])
            for path in created:
                if path not in sidecars:
                    sidecars.append(path)
            ctx.sidecar_paths = sidecars
            if self._sidecar_outputs is not None:
                self._sidecar_outputs[ctx.input_path] = sidecars

    def discard_prepared_nfo(self, ctx) -> None:
        # Waiting here is intentional on a failed conversion: otherwise the
        # daemon worker could publish a staging NFO after cleanup already ran.
        # Failed/aborted conversions only need to join the preparation thread
        # before deleting its staging file.  Do not probe/re-render a failed
        # or incomplete output merely to discard the result afterwards.
        self.await_prepared_nfo(ctx, refresh_technical=False)
        prepared = getattr(ctx, "prepared_nfo", None)
        ctx.prepared_nfo = None
        service = self._service
        discard = getattr(service, "discard_prepared_nfo", None) if service is not None else None
        if callable(discard):
            discard(prepared)

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
        from .postprocess_source_trickplay import discard_source_trickplay
        result = getattr(ctx, 'prepared_source_trickplay', None)
        ctx.prepared_source_trickplay = None
        discard_source_trickplay(result)

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
        self._merge_postprocess_items(ctx.input_path, details)
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

    def _merge_postprocess_items(self, input_path: str, details) -> None:
        if self._postprocess_outputs is None:
            return
        existing = [dict(item) for item in (self._postprocess_outputs.get(input_path, []) or [])]
        incoming = [dict(item) for item in (details or [])]
        self._postprocess_outputs[input_path] = existing + incoming
