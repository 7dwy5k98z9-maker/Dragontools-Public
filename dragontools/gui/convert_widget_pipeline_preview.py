"""Own asynchronous queue previews and reuse analysis when options change."""
from __future__ import annotations

import json
from copy import deepcopy

from PyQt6.QtCore import QObject, QTimer, Qt

from ..core.transaction_identity import stat_identity
from ..core.encoder_profile_override import file_override_may_enable_encoder_option
from ..worker.queue_pipeline_preview import QueuePipelinePreviewWorker


class ConvertWidgetPipelinePreview(QObject):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self._cache = {}
        self._media = {}
        self._pending = {}
        self._worker = None
        self._closed = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(20)
        self._timer.timeout.connect(self._start_pending)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._refresh_labels)

        for name in ("preserve_dv_cb", "preserve_hdrplus_cb", "autocrop_cb",
                     "hdr10plus_generator_quick_cb", "sdr_hdr_quick_cb"):
            checkbox = getattr(owner, name, None)
            if checkbox is not None:
                checkbox.toggled.connect(self.refresh)
        for name in ("encoder_combo", "scale_combo", "preset_combo"):
            combo = getattr(owner, name, None)
            if combo is not None:
                combo.currentIndexChanged.connect(self.refresh)
        owner.file_list.model().rowsRemoved.connect(self.refresh)

    def preview(self, path):
        if self._closed:
            return self._cache.get(path, (None, {}))[1]
        try:
            identity = stat_identity(path)
            options = self.owner.rule_test_preview_options(probe_generator=False)
            override = deepcopy(self.owner._state.file_overrides.get(path) or {})
            options.update(
                codec=self.owner.default_codec, file_override=override,
                subtitle_rules=deepcopy(self.owner.get_subtitle_rules()),
            )
            key = json.dumps([identity, options, repr(self.owner.tools)], sort_keys=True, default=str)
        except (OSError, ValueError) as exc:
            return {"error": str(exc)}
        cached = self._cache.get(path)
        if cached is not None and cached[0] == key:
            return cached[1]
        if self._worker is not None and self._worker.abort_requested:
            return {"pending": True}
        active = self._worker.jobs if self._worker is not None else ()
        if not any(job["path"] == path and job["key"] == key for job in active):
            media = self._media.get(path)
            self._pending[path] = {
                "path": path, "identity": identity, "key": key, "options": options,
                "media_info": media[1] if media is not None and media[0] == identity else None,
                "probe_generator": bool(
                    options["default_encoder_options"].get("hdr10plus_generator_enabled")
                    or override.get("generate_hdr10plus") is True
                    or file_override_may_enable_encoder_option(override, "hdr10plus_generator_enabled")
                ),
            }
            if self._worker is None and not self._timer.isActive():
                self._timer.start()
        return {"pending": True}

    def refresh(self, *_args):
        if not self._closed:
            self._refresh_timer.start(20)

    def _paths(self):
        file_list = self.owner.file_list
        return {
            file_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(file_list.count())
        } - {None}

    def _refresh_labels(self):
        paths = self._paths()
        for mapping in (self._cache, self._media, self._pending):
            for path in set(mapping) - paths:
                mapping.pop(path, None)
        for path in paths:
            self.owner.update_queue_label(path)

    def _start_pending(self):
        if self._closed or self._worker is not None:
            return
        paths = self._paths()
        jobs = [job for path, job in self._pending.items() if path in paths]
        self._pending.clear()
        if not jobs:
            return
        worker = QueuePipelinePreviewWorker(jobs, self.owner.tools, self)
        self._worker = worker
        worker.finished_with_result.connect(self._accept_result)
        worker.finished.connect(self._finished)
        try:
            worker.start()
        except RuntimeError as exc:
            self._worker = None
            worker.deleteLater()
            for job in jobs:
                self._cache[job["path"]] = (job["key"], {"error": str(exc)})
                self.owner.update_queue_label(job["path"])

    def _accept_result(self, result):
        if self._closed:
            return
        job, media_info, preview, error = result
        path = job["path"]
        if path not in self._paths():
            return
        try:
            if stat_identity(path) != job["identity"]:
                self.owner.update_queue_label(path)
                return
        except OSError:
            return
        if media_info is not None:
            self._media[path] = (job["identity"], media_info)
        self._cache[path] = (job["key"], {"error": error} if error else preview)
        self.owner.update_queue_label(path)

    def _finished(self):
        worker = self._worker
        self._worker = None
        if worker.abort_requested:
            self._closed = True
            self._pending.clear()
        worker.deleteLater()
        if self._pending and not self._closed:
            self._timer.start()

    def workers_for_shutdown(self):
        return (self._worker,) if self._worker is not None else ()

    def shutdown(self):
        self._closed = True
        self._timer.stop()
        self._refresh_timer.stop()
        self._pending.clear()
        if self._worker is not None:
            self._worker.request_abort()
