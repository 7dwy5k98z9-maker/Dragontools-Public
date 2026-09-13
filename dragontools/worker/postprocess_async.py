# -*- coding: utf-8 -*-
from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor, wait
from pathlib import Path

from ..core.settings import DEFAULT_TRICKPLAY_MAX_JOBS
from .log_dispatch import dispatch_log
from .postprocess_config import config_from_settings
from .postprocess_metadata import PostProcessMetadataSession
from .postprocess_models import PostProcessRunResult
from .postprocess_runner import PostProcessService


def postprocess_max_workers(settings) -> int:
    try:
        return config_from_settings(settings).trickplay.max_jobs
    except Exception:
        return DEFAULT_TRICKPLAY_MAX_JOBS


class AsyncPostProcessCoordinator:
    """Fuehrt NFO-/Trickplay-Nacharbeit im Hintergrund aus.

    Contract: ``submit()`` returns ``True`` only after a Future has been
    successfully scheduled *and* its completion callback has been attached.
    From that point on no best-effort logging failure may turn the result back
    into a synchronous fallback, otherwise the same file could be processed
    twice concurrently.
    """

    def __init__(self, *, settings, tools, log, worker=None, service_factory=None) -> None:
        self.settings = settings
        self.tools = tools
        self.log = log
        self.worker = worker
        self._metadata_session = PostProcessMetadataSession(settings) if service_factory is None else None
        self._service_factory = service_factory or (
            lambda: PostProcessService(
                settings=self.settings,
                tools=self.tools,
                log=self.log,
                worker=self.worker,
                metadata_session=self._metadata_session,
            )
        )
        self._executor = ThreadPoolExecutor(
            max_workers=postprocess_max_workers(settings),
            thread_name_prefix="DragonPostprocess",
        )
        self._futures: list[Future] = []
        self._lock = threading.Lock()
        self._shutdown = False

    def submit(
        self,
        *,
        input_path: str,
        output_path: str,
        existing_sidecars: list[str] | None,
        sidecar_outputs: dict[str, list[str]] | None,
        postprocess_outputs: dict[str, list[dict]] | None,
        result_service,
    ) -> bool:
        """Schedule one job without ever duplicating a successfully submitted job."""
        with self._lock:
            if self._shutdown:
                self._warn("Post-Processing konnte nicht gestartet werden: Coordinator ist bereits beendet.")
                return False
            try:
                service = self._service_factory()
                future = self._executor.submit(
                    service.run_result,
                    input_path=input_path,
                    output_path=output_path,
                )
                self._futures.append(future)
            except Exception as exc:
                self._warn(f"Post-Processing konnte nicht gestartet werden: {exc}")
                return False

        # Attach the callback before any non-essential operation. Once this
        # point is reached the Future owns the job and callers must not start a
        # second synchronous postprocess for the same file.
        try:
            future.add_done_callback(
                lambda done: self._complete_no_throw(
                    done,
                    input_path=input_path,
                    output_path=output_path,
                    existing_sidecars=existing_sidecars,
                    sidecar_outputs=sidecar_outputs,
                    postprocess_outputs=postprocess_outputs,
                    result_service=result_service,
                )
            )
        except Exception as exc:
            # add_done_callback() normally cannot fail for a valid Future. If
            # it does, the Future may already be running, so returning False
            # would risk a duplicate synchronous fallback. A tiny waiter thread
            # preserves exactly-once completion without resubmitting the job.
            self._warn(f"Post-Processing-Callback konnte nicht registriert werden: {exc}")
            threading.Thread(
                target=lambda: self._wait_and_complete(
                    future,
                    input_path=input_path,
                    output_path=output_path,
                    existing_sidecars=existing_sidecars,
                    sidecar_outputs=sidecar_outputs,
                    postprocess_outputs=postprocess_outputs,
                    result_service=result_service,
                ),
                name="DragonPostprocessCompletion",
                daemon=True,
            ).start()

        # Logging is intentionally last and fail-soft.
        self._info(f"🧩 Post-Processing im Hintergrund gestartet: {Path(output_path).name}")
        return True

    def wait_for_all(self) -> None:
        with self._lock:
            futures = list(self._futures)
            if self._shutdown:
                return
            self._shutdown = True
        if futures:
            self._info(f"🧩 Warte auf {len(futures)} Post-Processing-Auftrag/Aufträge ...")
            wait(futures)
        self._executor.shutdown(wait=True)

    def _wait_and_complete(self, future: Future, **kwargs) -> None:
        try:
            wait([future])
        finally:
            self._complete_no_throw(future, **kwargs)

    def _complete_no_throw(self, future: Future, **kwargs) -> None:
        """Future callback boundary: never leak an exception into concurrent.futures."""
        try:
            self._complete(future, **kwargs)
        except Exception as exc:
            # _complete() owns a finally-block that already attempts the file
            # completion signal exactly once. Do not emit a second result here.
            self._warn(f"Post-Processing-Abschlussfehler abgefangen: {exc}")

    def _complete(
        self,
        future: Future,
        *,
        input_path: str,
        output_path: str,
        existing_sidecars: list[str] | None,
        sidecar_outputs: dict[str, list[str]] | None,
        postprocess_outputs: dict[str, list[dict]] | None,
        result_service,
    ) -> None:
        try:
            result = future.result()
        except Exception as exc:
            self._warn(f"Post-Processing fehlgeschlagen: {exc}")
            result = PostProcessRunResult(
                [],
                [
                    {
                        "kind": "postprocess",
                        "status": "error",
                        "path": "",
                        "message": str(exc),
                    }
                ],
            )

        try:
            details = [dict(item) for item in (getattr(result, "items", []) or [])]
            if postprocess_outputs is not None:
                postprocess_outputs[input_path] = details

            sidecars = list(existing_sidecars or [])
            for path in list(getattr(result, "created_paths", []) or []):
                if path and path not in sidecars:
                    sidecars.append(path)
            if sidecar_outputs is not None:
                sidecar_outputs[input_path] = sidecars

            errors = [
                item for item in details
                if str(item.get("status", "")).lower() == "error"
            ]
            if errors:
                self._warn(f"🧩 Post-Processing mit Hinweis beendet: {Path(output_path).name}")
            else:
                self._info(f"🧩 Post-Processing abgeschlossen: {Path(output_path).name}")
        finally:
            # File completion belongs to the conversion workflow and must not
            # be skipped because bookkeeping or logging above failed.
            self._emit_completion_no_throw(
                result_service=result_service,
                input_path=input_path,
                output_path=output_path,
            )

    def _emit_completion_no_throw(self, *, result_service, input_path: str, output_path: str) -> None:
        if result_service is None:
            return
        try:
            result_service.emit_file_progress(input_path, 100)
            result_service.emit_file_result(input_path, output_path, "✅")
        except Exception as exc:
            self._warn(f"Post-Processing-Abschluss konnte nicht gemeldet werden: {exc}")

    def _info(self, message: str) -> None:
        dispatch_log(self.log, message, "info")

    def _warn(self, message: str) -> None:
        dispatch_log(self.log, message, "warn")
