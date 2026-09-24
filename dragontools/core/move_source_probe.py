# -*- coding: utf-8 -*-
"""Defensive source probing for move workflows.

A transient filesystem miss must never destroy move state.  This module keeps
probing and diagnostics independent from the Qt lifecycle code so both the GUI
pre-filter and the worker can apply the same rules.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


@dataclass(frozen=True)
class MoveSourceProbe:
    path: str
    available: bool
    size_bytes: int | None
    attempts: int
    error_type: str = ""
    error_message: str = ""
    parent_available: bool | None = None
    parent_error_type: str = ""
    parent_error_message: str = ""

    @property
    def error_text(self) -> str:
        if not self.error_type and not self.error_message:
            return ""
        if self.error_type and self.error_message:
            return f"{self.error_type}: {self.error_message}"
        return self.error_type or self.error_message

    @property
    def parent_error_text(self) -> str:
        if not self.parent_error_type and not self.parent_error_message:
            return ""
        if self.parent_error_type and self.parent_error_message:
            return f"{self.parent_error_type}: {self.parent_error_message}"
        return self.parent_error_type or self.parent_error_message


def _probe_parent(path: Path) -> tuple[bool | None, str, str]:
    parent = path.parent
    if not str(parent):
        return None, "", ""
    try:
        parent.stat()
    except OSError as exc:
        return False, type(exc).__name__, str(exc)
    return True, "", ""


def probe_move_source(
    path: str,
    *,
    attempts: int = 3,
    retry_delay_s: float = 0.1,
    sleeper: Callable[[float], None] = time.sleep,
) -> MoveSourceProbe:
    """Probe a move source without collapsing a transient miss into deletion.

    ``Path.exists()`` deliberately hides the underlying ``OSError``.  For move
    diagnostics we instead use ``stat()`` and retain the final exception type
    and message.  Retries are intentionally short and only happen on failures.
    """
    text = str(path or "")
    source = Path(text)
    max_attempts = max(1, int(attempts))
    delay = max(0.0, float(retry_delay_s))
    last_error: OSError | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            stat_result = source.stat()
        except OSError as exc:
            last_error = exc
            if attempt < max_attempts and delay:
                sleeper(delay)
            continue
        parent_available, parent_error_type, parent_error_message = _probe_parent(source)
        return MoveSourceProbe(
            path=text,
            available=True,
            size_bytes=int(stat_result.st_size),
            attempts=attempt,
            parent_available=parent_available,
            parent_error_type=parent_error_type,
            parent_error_message=parent_error_message,
        )

    parent_available, parent_error_type, parent_error_message = _probe_parent(source)
    return MoveSourceProbe(
        path=text,
        available=False,
        size_bytes=None,
        attempts=max_attempts,
        error_type=type(last_error).__name__ if last_error is not None else "",
        error_message=str(last_error) if last_error is not None else "",
        parent_available=parent_available,
        parent_error_type=parent_error_type,
        parent_error_message=parent_error_message,
    )


def probe_companions(paths: Iterable[str]) -> list[tuple[str, bool, str]]:
    """Return compact availability diagnostics for already-known companions."""
    result: list[tuple[str, bool, str]] = []
    for raw in paths or []:
        text = str(raw or "").strip()
        if not text:
            continue
        try:
            Path(text).stat()
        except OSError as exc:
            result.append((text, False, f"{type(exc).__name__}: {exc}"))
        else:
            result.append((text, True, ""))
    return result
