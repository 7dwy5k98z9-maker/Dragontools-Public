# -*- coding: utf-8 -*-
from __future__ import annotations

import threading
from typing import Callable

from ..core.paths import display_name, normalize_user_path, path_compare_key
from .worker_contracts import RemoveFileStatus, normalize_worker_path


LogFn = Callable[[str, str], None]


class ConverterQueueState:
    """Thread-safe Live-Queue-Zustand für ConverterThread."""

    def __init__(self, files: list[str]):
        self.files = list(files)
        self.initial_total = len(self.files)
        self.lock = threading.Lock()
        self.current_file: str | None = None
        self.done_files: set[str] = set()
        self.skip_files: set[str] = set()
        self.pending_remove_files: set[str] = set()

    def add_file(self, path: str, log: LogFn) -> bool:
        path = normalize_user_path(path)
        path_n = path_compare_key(path)
        name = display_name(path)

        with self.lock:
            current_n = normalize_worker_path(self.current_file) if self.current_file else None
            files_n = {normalize_worker_path(p) for p in self.files}
            done_n = {normalize_worker_path(p) for p in self.done_files}

            if path_n == current_n or path_n in files_n or path_n in done_n:
                return False

            self.files.append(path)

        log(f"➕ Queue: {name} hinzugefügt.", "info")
        return True

    def remove_file(self, path: str, log: LogFn) -> RemoveFileStatus:
        path = normalize_user_path(path)
        path_n = path_compare_key(path)
        name = display_name(path)

        with self.lock:
            if self.current_file and normalize_worker_path(self.current_file) == path_n:
                if self.current_file in self.pending_remove_files:
                    log(f"'{name}' ist bereits zur Entfernung nach Abschluss vorgemerkt.", "info")
                    return RemoveFileStatus.CURRENT

                self.pending_remove_files.add(self.current_file)
                log(
                    f"'{name}' läuft gerade und wird nach Abschluss aus der Queue entfernt.",
                    "warn",
                )
                return RemoveFileStatus.PENDING_REMOVE

            for i, queued_path in enumerate(self.files):
                if normalize_worker_path(queued_path) == path_n:
                    del self.files[i]
                    self.skip_files.discard(queued_path)
                    self.pending_remove_files.discard(queued_path)
                    log(f"Queue: '{name}' entfernt.", "info")
                    return RemoveFileStatus.REMOVED

            # Datei wurde bereits erfolgreich verarbeitet – keine Warnung nötig.
            if any(normalize_worker_path(p) == path_n for p in self.done_files):
                return RemoveFileStatus.NOT_FOUND

        log(f"Queue: '{name}' war nicht mehr vorhanden.", "warn")
        return RemoveFileStatus.NOT_FOUND

    def is_current(self, path: str) -> bool:
        with self.lock:
            return self.current_file == path

    def reorder_waiting_files(self, new_order: list[str]) -> None:
        with self.lock:
            done_n = {normalize_worker_path(p) for p in self.done_files}
            skip_n = {normalize_worker_path(p) for p in self.skip_files}
            curr_n = normalize_worker_path(self.current_file) if self.current_file else None
            self.files = [
                p for p in list(new_order or [])
                if normalize_worker_path(p) not in done_n
                and normalize_worker_path(p) not in skip_n
                and normalize_worker_path(p) != curr_n
            ]

    def next_file(self, processed_count: int) -> tuple[str, int] | None:
        with self.lock:
            done_n = {normalize_worker_path(p) for p in self.done_files}
            while self.files and normalize_worker_path(self.files[0]) in done_n:
                self.files.pop(0)

            if not self.files:
                return None

            path = self.files[0]
            self.current_file = path
            total_now = processed_count + len(self.files)
            return path, total_now

    def complete_current(self, path: str) -> None:
        with self.lock:
            self.done_files.add(path)
            self.pending_remove_files.discard(path)
            self.current_file = None
            if self.files and self.files[0] == path:
                self.files.pop(0)

    def total_after_processed(self, processed_count: int) -> int:
        with self.lock:
            return processed_count + len(self.files)
