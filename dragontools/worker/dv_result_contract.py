# -*- coding: utf-8 -*-
"""Terminal result/failure contract shared by all direct-DV worker paths."""
from __future__ import annotations

from pathlib import Path

from .worker_events import progress_event, result_event

_TERMINAL = {"✅", "❌", "⚠️", "⏭️"}


def _terminal_inputs(worker) -> set[str]:
    values = getattr(worker, "_dv_terminal_inputs", None)
    if not isinstance(values, set):
        values = set()
        setattr(worker, "_dv_terminal_inputs", values)
    return values


def mark_dv_terminal(worker, input_path: str, status: str) -> None:
    if str(status) in _TERMINAL:
        _terminal_inputs(worker).add(str(input_path))


def store_dv_failure(
    worker,
    input_path: str,
    reason: str,
    *,
    stage: str,
    pipeline: str = "dv_remux",
) -> None:
    details = getattr(worker, "_failure_details", None)
    if isinstance(details, dict):
        details[str(input_path)] = {
            "message": str(reason or "DV-Remux fehlgeschlagen."),
            "error_report": "",
            "pipeline": str(pipeline or "dv_remux"),
            "container": str(getattr(worker, "container", "") or ""),
            "strategy": str(stage or "dv_remux"),
        }


def emit_dv_result(
    worker,
    input_path: str,
    output_path: str,
    status: str,
    *,
    reason: str = "",
    stage: str = "dv_remux",
    progress: int | None = None,
) -> None:
    input_path = str(input_path)
    output_path = str(output_path or input_path)
    if reason:
        store_dv_failure(worker, input_path, reason, stage=stage)
    mark_dv_terminal(worker, input_path, status)
    worker.event.emit(result_event(input_path, output_path, status))
    worker.file_result.emit(input_path, output_path, status)
    if progress is not None:
        worker.event.emit(progress_event(input_path, int(progress), None))
        worker.file_progress.emit(input_path, int(progress), None)


def emit_dv_failure(
    worker,
    input_path: str,
    reason: str,
    *,
    stage: str = "dv_remux",
    output_path: str | None = None,
    status: str = "❌",
) -> None:
    emit_dv_result(
        worker,
        input_path,
        output_path or input_path,
        status,
        reason=reason,
        stage=stage,
        progress=100,
    )


def fail_unfinished_dv_inputs(worker, reason: str, *, stage: str = "worker") -> list[str]:
    """Mark every still-open queue item terminally failed exactly once."""
    queue = getattr(worker, "_queue", None)
    if queue is None:
        return []
    with queue.lock:
        candidates = []
        if queue.current_file:
            candidates.append(queue.current_file)
        candidates.extend(queue.files)
        done = {str(path) for path in queue.done_files}
    terminal = _terminal_inputs(worker)
    emitted: list[str] = []
    seen: set[str] = set()
    for path in candidates:
        path = str(path)
        if not path or path in seen or path in done or path in terminal:
            continue
        seen.add(path)
        emit_dv_failure(worker, path, reason, stage=stage)
        emitted.append(path)
    return emitted


__all__ = [
    "emit_dv_failure",
    "emit_dv_result",
    "fail_unfinished_dv_inputs",
    "mark_dv_terminal",
    "store_dv_failure",
]
