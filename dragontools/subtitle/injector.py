# -*- coding: utf-8 -*-
"""
dragontools/subtitle/injector.py
Untertitel in MKV/MP4 einfuegen.
"""
from __future__ import annotations
from ..core.timeout_settings import get_timeout

from pathlib import Path
from typing import Callable

from ..worker.tool_runner import run_tool
from .tool_logging import log_tool_error as _log_tool_error


def inject_with_mkvmerge(
    video_path: str,
    sub_path: str,
    output_path: str,
    language: str = "de",
    forced: bool = False,
    logger: Callable[[str], None] | None = None,
    mkvmerge: str = "mkvmerge",
    worker=None,
    overwrite: bool = False,
) -> bool:
    cmd = [
        mkvmerge,
        "-o",
        output_path,
        video_path,
        "--language",
        f"0:{language}",
        "--track-name",
        "0:",
    ]
    if forced:
        cmd += ["--forced-track", "0:yes"]
    cmd.append(sub_path)
    output = Path(output_path)
    if output.exists() and not overwrite:
        if logger:
            logger(f"❌ Zieldatei existiert bereits und wird nicht überschrieben: {output_path}")
        return False
    try:
        result = run_tool(
            cmd,
            label="Subtitle-Injection mkvmerge",
            timeout_s=get_timeout("subtitle_inject"),
            worker=worker,
            log=(lambda msg, level="info": logger(msg)) if logger else None,
        )
        ok = result.ok and output.exists() and output.stat().st_size > 0
        if not ok and logger:
            logger(f"❌ {Path(mkvmerge).name} lieferte keine Ausgabedatei: {output_path}")
        return ok
    except Exception as exc:
        _log_tool_error(logger, Path(mkvmerge).name, None, exc=exc)
        return False


def inject_with_ffmpeg(
    video_path: str,
    sub_path: str,
    output_path: str,
    language: str = "de",
    ffmpeg: str = "ffmpeg",
    logger: Callable[[str], None] | None = None,
    subtitle_codec: str | None = None,
    map_existing_subtitles: bool = True,
    worker=None,
    overwrite: bool = False,
) -> bool:
    cmd = [
        ffmpeg,
        "-y" if overwrite else "-n",
        "-nostdin",
        "-i",
        video_path,
        "-i",
        sub_path,
    ]
    if map_existing_subtitles:
        cmd += ["-map", "0", "-map", "1", "-c", "copy"]
    else:
        cmd += [
            "-map",
            "0:v?",
            "-map",
            "0:a?",
            "-map",
            "1:0",
            "-map_metadata",
            "0",
            "-map_chapters",
            "0",
            "-c:v",
            "copy",
            "-c:a",
            "copy",
        ]
    if subtitle_codec:
        cmd += ["-c:s", subtitle_codec]
    cmd += [
        "-metadata:s:s:0",
        f"language={language}",
        output_path,
    ]
    output = Path(output_path)
    if output.exists() and not overwrite:
        if logger:
            logger(f"❌ Zieldatei existiert bereits und wird nicht überschrieben: {output_path}")
        return False
    try:
        result = run_tool(
            cmd,
            label="Subtitle-Injection ffmpeg",
            timeout_s=get_timeout("subtitle_inject"),
            worker=worker,
            log=(lambda msg, level="info": logger(msg)) if logger else None,
        )
        ok = result.ok and output.exists() and output.stat().st_size > 0
        if not ok and logger:
            logger(f"❌ {Path(ffmpeg).name} lieferte keine Ausgabedatei: {output_path}")
        return ok
    except Exception as exc:
        _log_tool_error(logger, Path(ffmpeg).name, None, exc=exc)
        return False
