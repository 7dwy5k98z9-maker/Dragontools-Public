# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkerEvent:
    """Strukturiertes Worker-Ereignis neben den bestehenden GUI-Signalen."""

    type: str
    severity: str = "info"
    message: str = ""
    path: str | None = None
    percent: int | None = None
    eta: float | None = None
    output_path: str | None = None
    status: str | None = None


def progress_event(path: str, percent: int, eta: float | None = None) -> WorkerEvent:
    return WorkerEvent(
        type="progress",
        severity="info",
        path=path,
        percent=max(0, min(100, int(percent))),
        eta=eta,
    )


def result_event(path: str, output_path: str, status: str) -> WorkerEvent:
    severity = (
        "success" if status == "✅"
        else "error" if status == "❌"
        else "warning" if status == "\u26a0\ufe0f"
        else "info"
    )
    return WorkerEvent(
        type="result",
        severity=severity,
        path=path,
        output_path=output_path,
        status=status,
    )


def log_event(message: str, severity: str = "info", path: str | None = None) -> WorkerEvent:
    return WorkerEvent(type="log", severity=severity, message=message, path=path)
