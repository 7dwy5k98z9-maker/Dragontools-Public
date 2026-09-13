# -*- coding: utf-8 -*-
"""Compatibility facade for ffmpeg stream argument construction."""
from __future__ import annotations

import os
import tempfile
import traceback
from pathlib import Path

from .converter_audio_args import build_audio_args, build_audio_input_args
from .converter_subtitle_args import build_subtitle_args
from .converter_video_filter_args import base_vf_args as _base_vf_args, image_burn_vf_args as _image_burn_vf_args
from .tool_runner import run_tool


def _subtitle_rules(worker):
    job = getattr(worker, "_job_state", None)
    return job.subtitle_rules if job is not None else getattr(worker, "subtitle_rules")


def _tools(worker):
    services = getattr(worker, "_services", None)
    tools = getattr(services, "tools", None) if services is not None else None
    return tools if tools is not None else getattr(worker, "tools")


def _set_burn_sub_tmp(worker, value: str | None) -> None:
    temp_state = getattr(worker, "_temp_state", None)
    if temp_state is not None:
        temp_state.burn_sub_tmp = value
    else:
        worker._burn_sub_tmp = value


class BurnSubtitlePreparationError(RuntimeError):
    """Ein geplanter Subtitle-Burn-In konnte nicht sicher vorbereitet werden."""


def _esc(p: str) -> str:
    return p.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


class ConverterStreamArgsHelper:
    """Stable facade; audio/subtitle/filter planning lives in dedicated modules."""

    def __init__(self, worker):
        self.worker = worker

    def audio_args(self, mi, ov, container):
        return build_audio_args(self.worker, mi, ov, container)

    def audio_input_args(self, mi, ov, container):
        return build_audio_input_args(mi, ov, container)

    def sub_args(self, input_path, mi, ov, container="mkv"):
        return build_subtitle_args(self.worker, input_path, mi, ov, container=container, subtitle_rules=_subtitle_rules(self.worker))

    def base_vf_args(self, pre_filters: list[str], post_filters: list[str] | None = None) -> list:
        return _base_vf_args(pre_filters, post_filters)

    def text_burn_vf_args(self, input_path: str, output_path: str, burn_sub, pre_filters: list[str], post_filters: list[str] | None = None) -> list:
        worker = self.worker
        sub_tmp = tempfile.NamedTemporaryFile(suffix=".srt", delete=False, dir=Path(output_path).parent)
        sub_tmp.close()
        sub_tmp_path = sub_tmp.name
        completed = run_tool(
            [_tools(worker).ffmpeg, "-y", "-nostdin", "-loglevel", "error", "-i", input_path,
             "-map", f"0:{burn_sub.index}", "-c:s", "srt", sub_tmp_path],
            label=f"Burn-In Untertitel #{burn_sub.index}", timeout_s=300, worker=worker, log=worker.log,
        )
        ok = completed.returncode == 0 and not completed.aborted and not completed.timed_out
        detail = str(completed.stderr or completed.stdout or "").strip()
        if completed.aborted:
            detail = detail or "Abgebrochen"
        elif completed.timed_out:
            detail = detail or "Timeout"
        if ok and Path(sub_tmp_path).exists() and Path(sub_tmp_path).stat().st_size > 0:
            filters = pre_filters + [f"subtitles='{_esc(sub_tmp_path)}'"] + list(post_filters or [])
            _set_burn_sub_tmp(worker, sub_tmp_path)
            return ["-map", "0:v:0", "-vf", ",".join(filters)]
        worker.log("❌ Geplanter Burn-In konnte nicht vorbereitet werden; die Konvertierung wird nicht ohne den vorgesehenen Untertitel fortgesetzt.", "error")
        try:
            os.unlink(sub_tmp_path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            worker.log(f"⚠️ Temporäre Datei konnte nicht gelöscht werden: {Path(sub_tmp_path).name} - {exc}", "warn")
            worker.log(traceback.format_exc(), "error")
        suffix = f" ({detail})" if detail else ""
        raise BurnSubtitlePreparationError(f"Untertitel-Stream #{burn_sub.index} konnte nicht als SRT für den Burn-In vorbereitet werden{suffix}.")

    def image_burn_vf_args(self, mi, burn_sub, pre_filters: list[str], post_filters: list[str] | None = None) -> list:
        return _image_burn_vf_args(mi, burn_sub, pre_filters, post_filters)

    def build_vf_args(self, input_path: str, output_path: str, mi, burn_sub_or_vf, pre_filters: list[str], post_filters: list[str] | None = None) -> list:
        if not burn_sub_or_vf or isinstance(burn_sub_or_vf, list):
            return self.base_vf_args(pre_filters, post_filters)
        burn_sub = burn_sub_or_vf
        from ..rules.subtitle_rules import IMAGE_SUBTITLE_CODECS, TEXT_SUBTITLE_CODECS
        codec = (burn_sub.codec or "").lower()
        if codec in TEXT_SUBTITLE_CODECS:
            return self.text_burn_vf_args(input_path, output_path, burn_sub, pre_filters, post_filters)
        if codec in IMAGE_SUBTITLE_CODECS:
            return self.image_burn_vf_args(mi, burn_sub, pre_filters, post_filters)
        self.worker.log(f"❌ Burn-Sub #{burn_sub.index} hat einen nicht unterstützten Codec: {burn_sub.codec!r}", "error")
        raise BurnSubtitlePreparationError(f"Geplanter Burn-In verwendet einen nicht unterstützten Codec: {burn_sub.codec!r}.")
