# -*- coding: utf-8 -*-
"""
dragontools/subtitle/extractor.py
Untertitel aus MKV/MP4 extrahieren (mkvextract / ffmpeg).
"""
from __future__ import annotations
from ..core.timeout_settings import get_timeout
from pathlib import Path
from typing import Callable

from ..worker.tool_runner import run_tool
from .tool_logging import log_tool_error as _log_tool_error

def extract_with_ffmpeg(input_path: str, stream_index: int, output_path: str,
                        ffmpeg: str = "ffmpeg",
                        logger: Callable[[str], None] | None = None,
                        codec_args: list[str] | tuple[str, ...] | None = None,
                        worker=None,
                        overwrite: bool = False) -> bool:
    codec_args = list(codec_args or ["-c", "copy"])
    output = Path(output_path)
    if output.exists() and not overwrite:
        if logger:
            logger(f"❌ Zieldatei existiert bereits und wird nicht überschrieben: {output_path}")
        return False
    cmd = [
        ffmpeg, "-y" if overwrite else "-n", "-nostdin", "-i", input_path,
        "-map", f"0:{stream_index}", *codec_args, output_path,
    ]
    try:
        result = run_tool(
            cmd,
            label="Subtitle-Extraktion",
            timeout_s=get_timeout("subtitle_extract"),
            worker=worker,
            log=(lambda msg, level="info": logger(msg)) if logger else None,
        )
        ok = result.ok and output.exists() and output.stat().st_size > 0
        if not result.ok:
            _log_tool_error(logger, Path(ffmpeg).name, result.returncode, result.stdout, result.stderr)
        elif not ok and logger:
            logger(f"❌ {Path(ffmpeg).name} lieferte keine Ausgabedatei: {output_path}")
        return ok
    except Exception as exc:
        _log_tool_error(logger, Path(ffmpeg).name, None, exc=exc)
        return False

