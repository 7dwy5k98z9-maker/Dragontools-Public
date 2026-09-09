# -*- coding: utf-8 -*-
"""Koordinierter Shutdown aller von geladenen Haupt-Tabs gehaltenen Worker.

Das Modul ist absichtlich Qt-unabhängig. Die einzelnen Widgets exponieren über
``iter_shutdown_workers()`` nur ihre aktuell gehaltenen Worker. Dadurch kennt
MainWindow weder private Worker-Attribute noch konkrete Workerklassen.
"""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Iterable, Any


@dataclass(frozen=True)
class ApplicationShutdownResult:
    requested: int
    stopped: int
    still_running: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.still_running


def _worker_name(worker: Any) -> str:
    try:
        name = worker.objectName()
        if name:
            return str(name)
    except Exception:
        pass
    return worker.__class__.__name__


def _is_running(worker: Any) -> bool:
    try:
        return bool(worker.isRunning())
    except Exception:
        return False


def _request_stop(worker: Any) -> None:
    """Fordert einen kooperativen Sofort-Abbruch an, ohne QThread.terminate()."""
    request_abort = getattr(worker, "request_abort", None)
    if callable(request_abort):
        try:
            request_abort("sofort")
        except TypeError:
            request_abort()
        return

    cancel = getattr(worker, "cancel", None)
    if callable(cancel):
        cancel()
        return

    request_interruption = getattr(worker, "requestInterruption", None)
    if callable(request_interruption):
        request_interruption()


def _wait(worker: Any, timeout_ms: int) -> bool:
    if not _is_running(worker):
        return True
    wait = getattr(worker, "wait", None)
    if not callable(wait):
        return False
    try:
        return bool(wait(max(0, int(timeout_ms)))) or not _is_running(worker)
    except Exception:
        return not _is_running(worker)


def collect_shutdown_workers(widgets: Iterable[Any]) -> list[Any]:
    """Sammelt Worker ausschließlich über die öffentliche Widget-Schnittstelle."""
    workers: list[Any] = []
    seen: set[int] = set()
    for widget in widgets:
        if widget is None:
            continue
        provider = getattr(widget, "iter_shutdown_workers", None)
        if not callable(provider):
            continue
        try:
            provided = provider() or ()
        except Exception:
            continue
        for worker in provided:
            if worker is None:
                continue
            ident = id(worker)
            if ident in seen:
                continue
            seen.add(ident)
            workers.append(worker)
    return workers


def shutdown_workers(workers: Iterable[Any], *, timeout_ms: int = 8000) -> ApplicationShutdownResult:
    """Fordert alle Abbrüche zuerst an und wartet danach mit einem Gesamtbudget.

    Es wird bewusst kein ``QThread.terminate()`` verwendet. Bleibt ein Worker
    nach Ablauf des Budgets aktiv, muss die Anwendung offen bleiben; ein harter
    Thread-Abschuss könnte gerade während eines Datei-Commits Daten beschädigen.
    """
    unique: list[Any] = []
    seen: set[int] = set()
    for worker in workers:
        if worker is None or id(worker) in seen or not _is_running(worker):
            continue
        seen.add(id(worker))
        unique.append(worker)

    for worker in unique:
        try:
            _request_stop(worker)
        except Exception:
            # Ein fehlerhafter Worker darf nicht verhindern, dass die übrigen
            # Worker ebenfalls ihren Abbruch erhalten.
            continue

    deadline = time.monotonic() + max(0, int(timeout_ms)) / 1000.0
    for worker in unique:
        remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
        _wait(worker, remaining_ms)

    running = tuple(_worker_name(worker) for worker in unique if _is_running(worker))
    return ApplicationShutdownResult(
        requested=len(unique),
        stopped=len(unique) - len(running),
        still_running=running,
    )


def shutdown_loaded_widgets(widgets: Iterable[Any], *, timeout_ms: int = 8000) -> ApplicationShutdownResult:
    return shutdown_workers(collect_shutdown_workers(widgets), timeout_ms=timeout_ms)


__all__ = [
    "ApplicationShutdownResult",
    "collect_shutdown_workers",
    "shutdown_workers",
    "shutdown_loaded_widgets",
]
