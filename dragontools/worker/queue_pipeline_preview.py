"""Read-only queue previews using the converter's media and pipeline policy."""
from __future__ import annotations

from .base_worker import BaseWorker
from .utility_media_analysis import analyze_owned_media
from .hdr10plus_generator_client import HDR10PlusGeneratorClient, generator_executable_available
from ..core.media_analyzer import analyze_media
from ..core.rules_preview import build_rules_preview


class QueuePipelinePreviewWorker(BaseWorker):
    """A serial batch; every external probe belongs to this cancellable worker."""

    def __init__(self, jobs, tools, parent=None):
        super().__init__(parent)
        self.jobs = jobs
        self.tools = tools

    def _log(self, message, level="info"):
        self.log_line.emit(message)

    def run(self):
        generator_available = None
        for job in self.jobs:
            if self.abort_requested:
                break
            media_info = job.get("media_info")
            try:
                if media_info is None:
                    media_info = analyze_owned_media(
                        job["path"], self.tools, worker=self, analyzer=analyze_media,
                    )
                if getattr(media_info, "primary_video", None) is None:
                    raise RuntimeError("Keine verarbeitbare Videospur erkannt.")
                if not getattr(media_info, "ffmpeg_stream_indices_trusted", True):
                    raise RuntimeError("Keine verlässliche Spurzuordnung verfügbar.")
                options = dict(job["options"])
                if job["probe_generator"]:
                    if generator_available is None:
                        generator_available = self._generator_available()
                    options["hdr10plus_generator_available"] = generator_available
                    options["default_encoder_options"] = dict(options["default_encoder_options"])
                    options["default_encoder_options"]["_hdr10plus_generator_available"] = generator_available
                preview = build_rules_preview(
                    job["path"], tools=self.tools, media_info=media_info, **options,
                )
                error = ""
            except Exception as exc:
                preview, error = {}, str(exc)
            if not self.abort_requested:
                self.finished_with_result.emit((job, media_info, preview, error))

    def _generator_available(self):
        path = str(getattr(self.tools, "hdr10plus_generator", "") or "")
        if not generator_executable_available(path):
            return False
        result = HDR10PlusGeneratorClient(
            path, worker=self, log=self._log,
            ffmpeg_path=getattr(self.tools, "ffmpeg", "ffmpeg"),
            ffprobe_path=getattr(self.tools, "ffprobe", "ffprobe"),
        ).probe_version()
        return bool(result.success and result.version)
