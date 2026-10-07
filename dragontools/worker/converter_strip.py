# -*- coding: utf-8 -*-
"""Strip-only converter facade: video copy plus rule-driven audio/subtitle handling."""
from __future__ import annotations

from .converter_strip_audio import build_strip_audio_args
from .converter_strip_movtext_fallback import retry_with_mov_text_backup, run_strip_command
from .converter_strip_sidecars import export_strip_sidecars
from .converter_strip_subtitles import build_strip_subtitle_args
from .required_sidecar_step import finalize_required_sidecars


class ConverterStripHelper:
    """Kapselt den Strip-Only-Modus (Video-Copy, Audio/Subs nach Regeln)."""

    def __init__(self, worker):
        self.worker = worker
        self.last_sidecar_paths: list[str] = []
        self.last_externalized_subtitle_stream_indices: tuple[int, ...] = ()
        self.last_preserve_failed_output = False
        self.last_failure_reason = ""
        self.last_returncode = None

    def _record_returncode(self, returncode):
        self.last_returncode = returncode

    def strip_only(self, inp: str, out: str, mi, ov: dict | None = None, container: str = "mkv") -> bool:
        worker = self.worker
        self.last_preserve_failed_output = False
        self.last_failure_reason = ""
        self.last_returncode = None
        self.last_sidecar_paths = []
        self.last_externalized_subtitle_stream_indices = ()
        worker.log(
            "ℹ️ Strip-Only: Video-Copy. Audio- und Subtitle-Auswahl nach konfigurierten Regeln und Overrides "
            "(Audio wird ggf. transcodiert wenn Regeln es erfordern).",
            "info",
        )
        audio_input_args, audio_args = build_strip_audio_args(mi, ov, container)
        subtitle_args = build_strip_subtitle_args(worker, mi, ov, container)
        ok = run_strip_command(
            worker, inp=inp, out=out, container=container,
            audio_input_args=audio_input_args, audio_args=audio_args, subtitle_args=subtitle_args, media_info=mi,
            on_returncode=self._record_returncode,
        )
        self.last_sidecar_paths = []
        self.last_externalized_subtitle_stream_indices = ()
        fallback_paths: list[str] = []
        if not ok:
            if self.last_returncode in {124, 130}:
                return False
            fallback = retry_with_mov_text_backup(
                worker, inp=inp, out=out, mi=mi, ov=ov, container=container,
                audio_input_args=audio_input_args, audio_args=audio_args,
            )
            if not fallback.attempted or not fallback.success:
                self.last_sidecar_paths = list(fallback.sidecar_paths)
                return False
            fallback_paths = list(fallback.sidecar_paths)
            self.last_externalized_subtitle_stream_indices = fallback.externalized_stream_indices
        def export_step():
            complete, paths = export_strip_sidecars(
                worker, input_path=inp, output_path=out, media_info=mi, file_override=ov, container=container)
            return complete, paths, "Sidecar-Export unvollständig."
        result = finalize_required_sidecars(export_step, initial_sidecars=fallback_paths,
            externalized_indices=self.last_externalized_subtitle_stream_indices)
        self.last_sidecar_paths = list(result.sidecar_paths)
        self.last_preserve_failed_output = result.preserve_failed_output
        self.last_failure_reason = result.failure_reason
        if not result.success:
            worker.log(result.failure_reason, "error")
        return result.success
