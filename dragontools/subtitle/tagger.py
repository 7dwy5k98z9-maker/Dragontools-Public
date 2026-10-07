# -*- coding: utf-8 -*-
"""Sprach-Tags und Flags in MKV-Containern setzen (via mkvpropedit)."""
from __future__ import annotations
from ..worker.log_dispatch import dispatch_log

from typing import Callable

from ..core.tool_paths import get_tool_paths
from ..core.process_runner import run_analysis_tool
from ..core.timeout_settings import get_timeout
from .tool_logging import log_tool_error as _log_tool_error
from .output_safety import stopped
from .tag_edit_verification import verify_tag_edit


def _run_mkvpropedit(
    mkv_path: str,
    track_index: int,
    set_expression: str,
    *,
    logger: Callable[[str], None] | None = None,
) -> bool:
    if type(track_index) is not int or track_index < 0:
        return False
    tools = get_tool_paths()
    tool = tools.mkvpropedit
    # ``track:n`` adressiert den n-ten Track (1-basiert). ``track:@n`` waere
    # dagegen die Matroska TrackNumber und darf nicht aus einem GUI-Index gebaut werden.
    cmd = [
        tool, mkv_path,
        "--edit", f"track:{int(track_index) + 1}",
        "--set", set_expression,
    ]
    try:
        result = run_analysis_tool(
            cmd,
            allow_error=True,
            timeout=get_timeout("subtitle_tag"),
        )
        if stopped(result) or result.returncode not in {0, 1}:
            return False
        if not verify_tag_edit(mkv_path, track_index, set_expression,
                mkvmerge=getattr(tools, "mkvmerge", "mkvmerge"), run=run_analysis_tool):
            if logger:
                dispatch_log(logger, "❌ Die gewünschte Track-Änderung konnte nicht bestätigt werden.")
            return False
    except Exception as exc:
        _log_tool_error(logger, "mkvpropedit", None, exc=exc)
        return False

    if result.returncode == 1:
        if logger is not None:
            dispatch_log(logger, "⚠️ mkvpropedit meldet eine Warnung (Returncode 1); die Änderung wurde angewendet.")
        return True
    if result.returncode != 0:
        _log_tool_error(logger, "mkvpropedit", result.returncode, result.stdout, result.stderr)
        return False
    return True


def set_track_language(
    mkv_path: str,
    track_id: int,
    language: str = "de",
    logger: Callable[[str], None] | None = None,
) -> bool:
    return _run_mkvpropedit(
        mkv_path,
        track_id,
        f"language={language}",
        logger=logger,
    )


def set_forced_flag(
    mkv_path: str,
    track_id: int,
    forced: bool = True,
    logger: Callable[[str], None] | None = None,
) -> bool:
    return _run_mkvpropedit(
        mkv_path,
        track_id,
        f"flag-forced={'1' if forced else '0'}",
        logger=logger,
    )
