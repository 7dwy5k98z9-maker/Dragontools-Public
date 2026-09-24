# -*- coding: utf-8 -*-
"""Mixin exposing Fix Queue actions without growing the main dialog class."""
from __future__ import annotations

from .media_library_fix_controller import MediaLibraryFixController


class MediaLibraryFixActionsMixin:
    def _init_fix_controller(self) -> None:
        self._fix = MediaLibraryFixController(
            parent=self,
            view=self._view,
            service=self._service,
            settings=self.settings,
            get_db_path=self._db_path,
            refresh_stats=self._refresh_stats,
            other_task_running=lambda: self._scan.is_running or self._nfo.is_running,
        )

    def scan_fix_issues(self) -> None:
        self._fix.scan()

    def queue_selected_fix_issues(self) -> None:
        self._fix.add_selected()

    def queue_all_fix_issues(self) -> None:
        self._fix.add_all()

    def remove_selected_fix_items(self) -> None:
        self._fix.remove_selected()

    def clear_fix_queue(self) -> None:
        self._fix.clear()

    def run_fix_queue(self) -> None:
        self._fix.run()

    def abort_fix_queue(self) -> None:
        self._fix.abort()

    def review_selected_ocr_draft(self) -> None:
        self._fix.review_selected_ocr_draft()


__all__ = ["MediaLibraryFixActionsMixin"]
