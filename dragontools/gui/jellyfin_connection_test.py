# -*- coding: utf-8 -*-
"""Qt worker for non-blocking Jellyfin connection tests."""
from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal

from ..core.jellyfin_api import JellyfinClient


class JellyfinConnectionTestThread(QThread):
    completed = pyqtSignal(bool, str)

    def __init__(self, server_url: str, api_key: str) -> None:
        super().__init__()
        self._server_url = str(server_url or "")
        self._api_key = str(api_key or "")
        from . import jellyfin_refresh_dispatch as dispatch
        dispatch._ACTIVE_WORKERS.add(self)
        self.finished.connect(lambda: dispatch._ACTIVE_WORKERS.discard(self))

    def run(self) -> None:
        try:
            client = JellyfinClient(self._server_url, self._api_key)
            info = client.get_system_info()
            physical_paths = client.get_physical_paths()
        except Exception as exc:
            self.completed.emit(False, str(exc))
            return
        label = f"{info.server_name} · Jellyfin {info.version}"
        if info.operating_system:
            label += f" · {info.operating_system}"
        label += " · Pfade: " + ", ".join(physical_paths)
        self.completed.emit(True, label)
