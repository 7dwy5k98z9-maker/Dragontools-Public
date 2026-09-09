# -*- coding: utf-8 -*-
"""Qt-independent state models for parallel conversion coordination."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..core.paths import path_compare_key


@dataclass
class ParallelQueueState:
    files: list[str]
    pending_files: list[str] = field(init=False)
    assigned: dict[str, object] = field(default_factory=dict)
    file_progress_pct: dict[str, int] = field(default_factory=dict)
    terminal_inputs: set[str] = field(default_factory=set)
    postprocessing_inputs: set[str] = field(default_factory=set)
    display_index_by_path: dict[str, int] = field(default_factory=dict)
    display_total: int = 0

    def __post_init__(self) -> None:
        self.files = list(self.files)
        self.pending_files = list(self.files)
        self.rebuild_display_positions()

    def rebuild_display_positions(self) -> None:
        self.display_total = len(self.files)
        self.display_index_by_path = {
            path_compare_key(path): index
            for index, path in enumerate(self.files, start=1)
        }

    def aggregate_progress_percent(self) -> int:
        total = max(1, len(self.files))
        active_fraction = sum(
            max(0, min(100, pct)) / 100.0
            for path, pct in self.file_progress_pct.items()
            if path not in self.terminal_inputs
        )
        value = int(((len(self.terminal_inputs) + active_fraction) / total) * 100)
        return max(0, min(100, value))

    def display_position(self, path: str, fallback_idx: int, fallback_total: int) -> tuple[int, int]:
        try:
            idx = int(self.display_index_by_path.get(path_compare_key(path), fallback_idx))
        except Exception:
            idx = fallback_idx
        try:
            total = int(self.display_total or fallback_total)
        except Exception:
            total = fallback_total
        return max(1, idx), max(1, total)

    def reorder(self, order: list[str]) -> None:
        pending_by_key = {path_compare_key(path): path for path in self.pending_files}
        seen_pending: set[str] = set()
        reordered_pending: list[str] = []
        for path in order:
            key = path_compare_key(path)
            if key in pending_by_key and key not in seen_pending:
                reordered_pending.append(pending_by_key[key])
                seen_pending.add(key)
        for path in self.pending_files:
            key = path_compare_key(path)
            if key not in seen_pending:
                reordered_pending.append(path)
                seen_pending.add(key)
        self.pending_files = reordered_pending

        known_by_key = {path_compare_key(path): path for path in self.files}
        seen: set[str] = set()
        reordered_files: list[str] = []
        for path in order:
            key = path_compare_key(path)
            if key in known_by_key and key not in seen:
                reordered_files.append(known_by_key[key])
                seen.add(key)
        for path in self.files:
            key = path_compare_key(path)
            if key not in seen:
                reordered_files.append(path)
                seen.add(key)
        self.files = reordered_files
        self.rebuild_display_positions()


@dataclass
class ParallelResultState:
    sidecar_outputs: dict[str, list[str]] = field(default_factory=dict)
    postprocess_outputs: dict[str, list[dict]] = field(default_factory=dict)
    failure_details: dict[str, dict] = field(default_factory=dict)
    synthetic_failures: int = 0

    def sync_from_child(self, child, input_path: str | None = None) -> None:
        sidecars = getattr(child, "_sidecar_outputs", {}) or {}
        postprocess = getattr(child, "_postprocess_outputs", {}) or {}
        failures = getattr(child, "_failure_details", {}) or {}
        if input_path:
            if input_path in sidecars:
                self.sidecar_outputs[input_path] = list(sidecars.get(input_path) or [])
            if input_path in postprocess:
                self.postprocess_outputs[input_path] = [
                    dict(item) for item in (postprocess.get(input_path) or [])
                ]
            if input_path in failures:
                self.failure_details[input_path] = dict(failures.get(input_path) or {})
            return
        for path, values in sidecars.items():
            self.sidecar_outputs[path] = list(values or [])
        for path, values in postprocess.items():
            self.postprocess_outputs[path] = [dict(item) for item in (values or [])]
        for path, values in failures.items():
            self.failure_details[path] = dict(values or {})

@dataclass
class ParallelWorkerRegistry:
    queue_state: ParallelQueueState
    result_state: ParallelResultState
    workers: list[object] = field(default_factory=list)
    active_workers: set[object] = field(default_factory=set)
    postprocessing_workers: set[object] = field(default_factory=set)
    replace_service: object | None = None

    def active_count(self) -> int:
        return sum(1 for worker in self.active_workers if worker.isRunning())

    def sync_replace_service(self) -> None:
        if self.replace_service is None:
            return
        blocked: set[str] = set()
        archived = 0
        for worker in self.workers:
            service = getattr(worker, "_replace_service", None)
            if service is None:
                continue
            blocked.update(getattr(service, "blocked_move_inputs", set()) or set())
            archived += int(getattr(service, "archiviert", 0) or 0)
        self.replace_service.blocked_move_inputs = blocked
        self.replace_service.archiviert = archived

    def sync_child_maps(self, child, input_path: str | None = None) -> None:
        self.result_state.sync_from_child(child, input_path)
        self.sync_replace_service()

    def unreported_child_files(self, child) -> list[str]:
        terminal_keys = {
            path_compare_key(path)
            for path in (self.queue_state.terminal_inputs | self.queue_state.postprocessing_inputs)
        }
        candidates: list[str] = []
        for attr in ("_all_input_files", "files"):
            values = getattr(child, attr, None)
            if isinstance(values, (list, tuple, set)):
                candidates.extend(str(path) for path in values if str(path or ""))
        queue = getattr(child, "_queue", None)
        current = getattr(queue, "current_file", None)
        if current:
            candidates.append(str(current))
        queue_files = getattr(queue, "files", None)
        if isinstance(queue_files, (list, tuple, set)):
            candidates.extend(str(path) for path in queue_files if str(path or ""))
        candidates.extend(
            path
            for path in self.queue_state.files
            if self.queue_state.assigned.get(path_compare_key(path)) is child
        )

        result: list[str] = []
        seen: set[str] = set()
        for path in candidates:
            key = path_compare_key(path)
            if not key or key in seen or key in terminal_keys:
                continue
            seen.add(key)
            result.append(path)
        return result

    def diagnostic_workers(self) -> list[dict]:
        result: list[dict] = []
        for worker in list(self.active_workers | self.postprocessing_workers):
            if hasattr(worker, "diagnostic_snapshot"):
                try:
                    result.append(worker.diagnostic_snapshot())
                    continue
                except Exception:
                    pass
            result.append(
                {
                    "type": "converter",
                    "running": bool(worker.isRunning()) if hasattr(worker, "isRunning") else False,
                    "paused": bool(getattr(worker, "_paused", False)),
                    "abort_requested": bool(getattr(worker, "abort_requested", False)),
                    "abort_type": getattr(worker, "abort_type", "") or "",
                    "current_file": (getattr(worker, "files", []) or [""])[0],
                    "waiting_files": [],
                    "done_files": [],
                    "pending_remove_files": [],
                    "process_pid": None,
                    "process_command": "",
                }
            )
        return result
