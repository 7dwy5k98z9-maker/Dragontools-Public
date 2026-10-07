# -*- coding: utf-8 -*-
"""Small adapter that isolates optional move-journal interaction."""
from __future__ import annotations

from pathlib import Path
from .path_syntax import path_compare_key


class MoveJournalAdapter:
    def __init__(self, journal) -> None:
        self._journal = journal
        self._destinations = {}

    def tracks(self, source_path: str | Path) -> bool:
        if self._journal is None:
            return False
        data = getattr(self._journal, "data", {})
        files = data.get("files") if isinstance(data.get("files"), dict) else {}
        return any(path_compare_key(path) == path_compare_key(str(source_path)) for path in files)

    def set_commit_proof(self, source_path, source_receipt, destination_receipt):
        method = getattr(self._journal, 'set_commit_proof', None)
        if self.tracks(source_path) and callable(method):
            method(str(source_path), source_receipt, destination_receipt)
        elif not self.tracks(source_path):
            companion_method = getattr(self._journal, 'record_companion_proof', None)
            destination = self._destinations.get(path_compare_key(str(source_path)))
            if callable(companion_method) and destination is not None:
                companion_method(str(source_path), str(destination), source_receipt, destination_receipt)

    def set_destination(self, source_path: str | Path, dst_p: Path) -> None:
        self._destinations[path_compare_key(str(source_path))] = str(dst_p)
        if self.tracks(source_path):
            self._journal.set_destination(
                str(source_path), target_dir=str(dst_p.parent), dest_path=str(dst_p)
            )

    def set_backups(self, source_path: str | Path, pairs: list[dict[str, str]]) -> None:
        if self.tracks(source_path):
            self._journal.set_backups(str(source_path), pairs)

    def clear_backups(self, source_path: str | Path) -> None:
        if self.tracks(source_path):
            self._journal.clear_backups(str(source_path))

    def set_cleanup_pending(self, source_path: str | Path, message: str) -> None:
        if self.tracks(source_path):
            self._journal.set_cleanup_pending(str(source_path), message=message)
