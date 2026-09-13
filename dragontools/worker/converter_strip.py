# -*- coding: utf-8 -*-
"""Strip-only converter facade: video copy plus rule-driven audio/subtitle handling."""
from __future__ import annotations

from .converter_strip_audio import build_strip_audio_args
from .converter_strip_runtime import progress as _progress, subtitle_rules as _subtitle_rules, tools as _tools
from .converter_strip_sidecars import export_strip_sidecars
from .converter_strip_subtitles import build_strip_subtitle_args


def _job(worker):
    return getattr(worker, "_job_state", None)


def _services(worker):
    return getattr(worker, "_services", None)


class ConverterStripHelper:
    """Kapselt den Strip-Only-Modus (Video-Copy, Audio/Subs nach Regeln)."""

    def __init__(self, worker):
        self.worker = worker
        self.last_sidecar_paths: list[str] = []

    def strip_only(self, inp: str, out: str, mi, ov: dict | None = None, container: str = "mkv") -> bool:
        worker = self.worker
        worker.log(
            "ℹ️ Strip-Only: Video-Copy. Audio- und Subtitle-Auswahl nach konfigurierten Regeln und Overrides "
            "(Audio wird ggf. transcodiert wenn Regeln es erfordern).",
            "info",
        )
        audio_input_args, audio_args = build_strip_audio_args(mi, ov, container)
        subtitle_args = build_strip_subtitle_args(worker, mi, ov, container)
        cmd = [
            _tools(worker).ffmpeg, "-y", "-loglevel", "error",
            *audio_input_args, "-i", inp,
            *audio_args, *subtitle_args,
        ]
        if str(container or "mkv").lower() == "mp4":
            cmd += ["-movflags", "+faststart"]
        cmd += ["-map", "0:v:0", "-c:v", "copy", out]
        ok = _progress(worker).run(cmd) == 0
        self.last_sidecar_paths = []
        if not ok:
            return False
        sidecars_ok, paths = export_strip_sidecars(
            worker,
            input_path=inp,
            output_path=out,
            media_info=mi,
            file_override=ov,
            container=container,
        )
        self.last_sidecar_paths = paths
        return sidecars_ok
