# -*- coding: utf-8 -*-
"""
dragontools/subtitle/extractor.py
Untertitel aus MKV/MP4 extrahieren (mkvextract / ffmpeg).
"""
from __future__ import annotations
from ..worker.log_dispatch import dispatch_log
import uuid
from ..core.timeout_settings import get_timeout
from pathlib import Path
from typing import Callable

from ..worker.tool_runner import run_tool
from .tool_logging import log_tool_error as _log_tool_error
from .output_safety import publish_subtitle_stage, reject_source_output, stopped
from .media_verification import verify_extraction


def _staging_output(output: Path) -> Path:
    return output.with_name(f".{output.stem}.dragontools-{uuid.uuid4().hex}{output.suffix}")

def extract_with_ffmpeg(input_path: str, stream_index: int, output_path: str,
                        ffmpeg: str = "ffmpeg",
                        logger: Callable[[str], None] | None = None,
                        codec_args: list[str] | tuple[str, ...] | None = None,
                        worker=None,
                        overwrite: bool = False) -> bool:
    codec_args = list(codec_args or ["-c", "copy"])
    output = Path(output_path)
    if type(stream_index) is not int or stream_index < 0 or reject_source_output(output, input_path):
        return False
    if output.exists() and not overwrite:
        if logger:
            dispatch_log(logger, f"❌ Zieldatei existiert bereits und wird nicht überschrieben: {output_path}")
        return False
    stage = _staging_output(output)
    verified = False
    cmd = [
        ffmpeg, "-y" if overwrite else "-n", "-nostdin", "-i", input_path,
        "-map", f"0:{stream_index}", *codec_args, str(stage),
    ]
    try:
        result = run_tool(
            cmd,
            label="Subtitle-Extraktion",
            timeout_s=get_timeout("subtitle_extract"),
            worker=worker,
            log=(lambda msg, level="info": dispatch_log(logger, msg)) if logger else None,
        )
        try:
            valid = stage.exists() and stage.stat().st_size > 0
        except OSError:
            valid = False
        ok = result.ok and valid and not stopped(result, worker)
        if not result.ok or stopped(result, worker):
            stage.unlink(missing_ok=True)
            _log_tool_error(logger, Path(ffmpeg).name, result.returncode, result.stdout, result.stderr)
            return False
        if not ok:
            stage.unlink(missing_ok=True)
            if logger:
                dispatch_log(logger, f"❌ {Path(ffmpeg).name} lieferte keine Ausgabedatei: {output_path}")
            return False
        from .injector import _ffprobe_for_ffmpeg
        verify_extraction(stage, input_path=input_path, stream_index=stream_index,
            codec_args=codec_args, ffprobe=_ffprobe_for_ffmpeg(ffmpeg, None), worker=worker, logger=logger)
        if stopped(result, worker):
            stage.unlink(missing_ok=True)
            return False
        verified = True
        try:
            publish_subtitle_stage(stage, output, overwrite=overwrite)
        except OSError as exc:
            if logger:
                dispatch_log(logger, f"❌ Extraktions-Commit fehlgeschlagen; geprüfte Ausgabe bleibt erhalten: {stage}")
            _log_tool_error(logger, Path(ffmpeg).name, result.returncode, exc=exc)
            return False
        return True
    except Exception as exc:
        if not verified:
            stage.unlink(missing_ok=True)
        _log_tool_error(logger, Path(ffmpeg).name, None, exc=exc)
        return False
