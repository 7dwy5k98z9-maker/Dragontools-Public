# -*- coding: utf-8 -*-
"""Sprach-Tags und Flags in MKV-Containern setzen (via mkvpropedit)."""
from __future__ import annotations

from typing import Callable

from ..core.paths import get_tool_paths
from ..core.process_runner import run_analysis_tool
from ..core.timeout_settings import get_timeout
from .tool_logging import log_tool_error as _log_tool_error


def _run_mkvpropedit(
    mkv_path: str,
    track_index: int,
    set_expression: str,
    *,
    logger: Callable[[str], None] | None = None,
) -> bool:
    tool = get_tool_paths().mkvpropedit
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
    except Exception as exc:
        _log_tool_error(logger, "mkvpropedit", None, exc=exc)
        return False

    if result.returncode == 1:
        if logger is not None:
            logger("⚠️ mkvpropedit meldet eine Warnung (Returncode 1); die Änderung wurde angewendet.")
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
