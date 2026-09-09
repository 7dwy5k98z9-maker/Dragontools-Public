# -*- coding: utf-8 -*-
"""Small adapter that isolates optional move-journal interaction."""
from __future__ import annotations

from pathlib import Path


class MoveJournalAdapter:
    def __init__(self, journal) -> None:
        self._journal = journal

    def tracks(self, source_path: str | Path) -> bool:
        if self._journal is None:
            return False
        data = getattr(self._journal, "data", {})
        files = data.get("files") if isinstance(data.get("files"), dict) else {}
        return str(source_path) in files

    def set_destination(self, source_path: str | Path, dst_p: Path) -> None:
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
