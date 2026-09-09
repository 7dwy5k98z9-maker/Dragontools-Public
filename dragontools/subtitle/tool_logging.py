# -*- coding: utf-8 -*-
"""Gemeinsame Fehlerausgabe für externe Subtitle-Tools."""
from __future__ import annotations

from typing import Callable


def log_tool_error(
    logger: Callable[[str], None] | None,
    tool: str,
    rc: int | None,
    stdout: str | None = None,
    stderr: str | None = None,
    exc: Exception | None = None,
) -> None:
    if not logger:
        return
    if exc is not None:
        logger(f"❌ {tool} konnte nicht gestartet werden: {exc}")
        return
    logger(f"❌ {tool} fehlgeschlagen (rc={rc})")
    lines = [
        line.strip()
        for line in ((stderr or "") + "\n" + (stdout or "")).splitlines()
        if line.strip()
    ]
    for line in lines[-10:]:
        logger(f"  {tool}: {line}")


__all__ = ["log_tool_error"]
