# -*- coding: utf-8 -*-
"""Bridge from the DV-remux worker into the established P5 DV encode path."""
from __future__ import annotations

from copy import deepcopy

from ..core.conversion_artifacts import ConversionArtifactBundle, publish_bundle_to_worker
from .converter_config import ConverterConfig
from .dv_result_contract import emit_dv_failure, mark_dv_terminal

_TERMINAL_RESULTS = {"✅", "❌", "⚠️", "⏭️"}

# Lazy-loaded to keep the fallback service importable without a Qt runtime.
# Tests/extensions may still replace this compatibility hook explicitly.
ConverterThread = None


def _converter_thread_class():
    global ConverterThread
    if ConverterThread is None:
        from .converter_thread import ConverterThread as converter_thread_class
        ConverterThread = converter_thread_class
    return ConverterThread


class DV5EncodeFallbackRunner:
    """Run one Profile-5 source through the normal H.265 DV converter.

    The fallback intentionally reuses ``ConverterThread`` synchronously inside
    the DV-remux worker thread.  That avoids a second DV implementation and
    therefore keeps libplacebo colour conversion, RPU handling, validation,
    replacement and post-processing identical to a normal H.265 conversion.
    """

    def __init__(self, worker, config: ConverterConfig | None) -> None:
        self.worker = worker
        self._config = config

    def run(self, input_path: str) -> bool:
        if self._config is None:
            reason = "DV5-Encoding-Fallback wurde angefordert, aber keine Converter-Konfiguration übergeben."
            self.worker.log(f"❌ {reason}", "error")
            emit_dv_failure(self.worker, input_path, reason, stage="dv5_fallback_config")
            return False

        config = deepcopy(self._config)
        config.codec = "h265"
        config.strip_only = False
        config.file_overrides = {
            input_path: deepcopy(getattr(self.worker, "file_overrides", {}).get(input_path, {}))
        }
        options = dict(config.encoder_options or {})
        options["preserve_dv"] = True
        # Profile 5 has no normal HDR10 base layer.  Let the established DV
        # pipeline own the conversion instead of attempting an HDR10+-combo path.
        options["preserve_hdrplus"] = False
        config.encoder_options = options
        # The explicit DV-remux action is not a move/preflight action.  Keep the
        # fallback in the source location just like the remux result.
        config.tv_path = None
        config.anime_path = None
        config.filme_path = None

        child_class = _converter_thread_class()
        child = child_class([input_path], config, shared_logger=self.worker._logger)
        self.worker._active_fallback_worker = child
        child.file_progress.connect(self.worker.file_progress.emit)
        child.file_result.connect(
            lambda source, output, status: self._forward_file_result(
                child, source, output, status
            )
        )
        child.worker_event.connect(lambda event: self._forward_event(child, event))
        if hasattr(self.worker, "dv_crop_decision_requested"):
            child.dv_crop_decision_requested.connect(self.worker.dv_crop_decision_requested.emit)
        try:
            self.worker.log(
                "  🎨 DV5: Remux ist nicht zulässig – automatischer Wechsel in den normalen H.265-DV-Encodingpfad.",
                "warn",
            )
            # run() is called synchronously on purpose: the outer DVRemuxThread
            # remains the one batch worker visible to the GUI.
            child.run()
            # Final safety sync for workers/tests that do not emit a terminal
            # file_result signal. GUI consumers normally receive the same state
            # before the terminal signal via _forward_file_result/_forward_event.
            self._sync_child_state(child, input_path=input_path)
            return bool(child.erfolgreich > 0 and child.fehlgeschlagen == 0)
        finally:
            self.worker._active_fallback_worker = None

    def _forward_file_result(self, child, input_path: str, output_path: str, status: str) -> None:
        if status in _TERMINAL_RESULTS:
            self._sync_child_state(child, input_path=input_path)
            mark_dv_terminal(self.worker, input_path, status)
        self.worker.file_result.emit(input_path, output_path, status)

    def _forward_event(self, child, event) -> None:
        if (
            getattr(event, "type", None) == "result"
            and getattr(event, "status", None) in _TERMINAL_RESULTS
        ):
            path = str(getattr(event, "path", "") or "")
            self._sync_child_state(child, input_path=path)
            if path:
                mark_dv_terminal(self.worker, path, str(getattr(event, "status", "")))
        self.worker.worker_event.emit(event)

    def _sync_child_state(self, child, *, input_path: str = "") -> None:
        """Publish one coherent child artifact snapshot on the outer DV worker."""
        if input_path:
            publish_bundle_to_worker(
                self.worker,
                ConversionArtifactBundle.from_worker(child, input_path),
            )
            return
        session = getattr(child, "_session_state", None)
        keys: set[str] = set()
        for attr in ("sidecar_outputs", "postprocess_outputs", "failure_details"):
            mapping = getattr(session, attr, None) if session is not None else None
            if isinstance(mapping, dict):
                keys.update(str(key) for key in mapping)
        for key in keys:
            publish_bundle_to_worker(
                self.worker,
                ConversionArtifactBundle.from_worker(child, key),
            )

