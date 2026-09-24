# -*- coding: utf-8 -*-
"""
dragontools/subtitle/injector.py
Untertitel in MKV/MP4 einfuegen.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from ..core.timeout_settings import get_timeout
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


def _ffprobe_for_ffmpeg(ffmpeg: str, ffprobe: str | None) -> str:
    """Return an explicit ffprobe path or the sibling executable of ffmpeg."""
    if ffprobe:
        return ffprobe
    ffmpeg_path = Path(ffmpeg)
    suffix = ".exe" if ffmpeg_path.suffix.lower() == ".exe" else ""
    return str(ffmpeg_path.with_name(f"ffprobe{suffix}"))


def _probe_subtitle_count(
    video_path: str,
    *,
    ffprobe: str,
    logger: Callable[[str], None] | None = None,
    worker=None,
) -> int | None:
    """Return the number of subtitle streams in *video_path* or ``None`` on probe failure.

    The ffmpeg injection fallback keeps existing subtitle streams.  We therefore need
    their exact count so metadata/disposition can be written to the newly appended
    subtitle instead of accidentally modifying subtitle stream 0.
    """
    try:
        result = run_tool(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "s",
                "-show_entries",
                "stream=index",
                "-of",
                "json",
                video_path,
            ],
            label="Subtitle-Injection ffprobe",
            timeout_s=30,
            worker=worker,
            log=(lambda msg, level="info": logger(msg)) if logger else None,
        )
        if not result.ok:
            if logger:
                logger(
                    "❌ Untertitelanzahl konnte nicht ermittelt werden "
                    f"({Path(ffprobe).name}, rc={result.returncode})."
                )
            return None
        payload = json.loads(result.stdout or "{}")
        streams = payload.get("streams", [])
        if not isinstance(streams, list):
            raise ValueError("ffprobe lieferte kein gültiges streams-Array")
        return len(streams)
    except Exception as exc:
        _log_tool_error(logger, Path(ffprobe).name, None, exc=exc)
        return None


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
    forced: bool = False,
    ffprobe: str | None = None,
    existing_subtitle_count: int | None = None,
) -> bool:
    output = Path(output_path)
    if output.exists() and not overwrite:
        if logger:
            logger(f"❌ Zieldatei existiert bereits und wird nicht überschrieben: {output_path}")
        return False

    # With ``-map 0 -map 1`` the newly injected subtitle is appended after all
    # existing subtitle streams.  Resolve that output subtitle index before
    # constructing metadata/disposition arguments.  In MP4 text mode existing
    # subtitles are intentionally excluded, so the new stream is always s:0.
    if map_existing_subtitles:
        if existing_subtitle_count is None:
            existing_subtitle_count = _probe_subtitle_count(
                video_path,
                ffprobe=_ffprobe_for_ffmpeg(ffmpeg, ffprobe),
                logger=logger,
                worker=worker,
            )
        if existing_subtitle_count is None:
            if logger:
                logger(
                    "❌ Injection abgebrochen: Der neue Untertitel-Index ist nicht sicher bestimmbar."
                )
            return False
        if existing_subtitle_count < 0:
            if logger:
                logger("❌ Injection abgebrochen: Ungültige Anzahl vorhandener Untertitel.")
            return False
        new_subtitle_index = existing_subtitle_count
    else:
        new_subtitle_index = 0

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
        f"-metadata:s:s:{new_subtitle_index}",
        f"language={language}",
        f"-disposition:s:{new_subtitle_index}",
        "forced" if forced else "0",
        output_path,
    ]
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

