# -*- coding: utf-8 -*-
from __future__ import annotations

import threading

from ..core.online_metadata import client_from_settings_for


class PostProcessMetadataSession:
    """Shared metadata clients for one post-processing batch.

    The session reuses provider authentication and the provider clients' in-memory
    batch caches across all parallel NFO jobs.  Episode metadata is refreshed once
    per provider/session and then reused for sibling episodes of the same series.
    """

    def __init__(self, settings) -> None:
        self._settings = settings
        self._clients: dict[str, object] = {}
        self._lock = threading.Lock()

    def client(self, media_type: str):
        key = str(media_type or "").casefold()
        with self._lock:
            client = self._clients.get(key)
            if client is None:
                client = client_from_settings_for(self._settings, key, require_enabled=True)
                enable_fresh = getattr(client, "enable_fresh_session", None)
                if callable(enable_fresh):
                    enable_fresh()
                self._clients[key] = client
            return client

    def resolve_episode_file(self, path: str):
        client = self.client("series")
        refresh = getattr(client, "refresh_episode_candidates", None)
        if callable(refresh):
            suggestions = refresh(path, limit=1)
            return suggestions[0] if suggestions else None
        return client.resolve_episode_file(path)

    def resolve_movie_file(self, path: str):
        return self.client("movie").resolve_movie_file(path)
