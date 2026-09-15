# -*- coding: utf-8 -*-
from __future__ import annotations

import threading

from ..core.online_metadata import client_from_settings_for
from .postprocess_metadata_resolution import (
    MetadataResolution, episode_resolution, movie_ambiguity,
    episode_candidate_buckets_for_postprocess, movie_candidate_buckets_for_postprocess,
    resolve_episode_candidates_for_postprocess, resolve_movie_search_for_postprocess,
)


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

    def resolve_episode(self, path: str, *, require_unambiguous: bool = False) -> MetadataResolution:
        client = self.client("series")
        if not require_unambiguous:
            refresh = getattr(client, "refresh_episode_candidates", None)
            if callable(refresh):
                suggestions = refresh(path, limit=1)
                suggestion = suggestions[0] if suggestions else None
            else:
                suggestion = client.resolve_episode_file(path)
            return MetadataResolution(suggestion, False, "", 1 if suggestion is not None else 0)

        first_ambiguous: MetadataResolution | None = None
        for _provider, candidates in episode_candidate_buckets_for_postprocess(client, path, limit=4):
            resolution = episode_resolution(candidates, path)
            if resolution.suggestion is not None and not resolution.ambiguous:
                return resolution
            if first_ambiguous is None and resolution.ambiguous:
                first_ambiguous = resolution
        return first_ambiguous or MetadataResolution(None, False, "Keine passende Serienfolge gefunden.", 0)

    def resolve_episode_file(self, path: str):
        return self.resolve_episode(path, require_unambiguous=False).suggestion

    def resolve_movie(self, path: str, *, require_unambiguous: bool = False) -> MetadataResolution:
        client = self.client("movie")
        if require_unambiguous:
            first_ambiguous: MetadataResolution | None = None
            for provider, records in movie_candidate_buckets_for_postprocess(client, path, limit=6):
                ambiguity = movie_ambiguity(records, path)
                if ambiguity.ambiguous:
                    if first_ambiguous is None:
                        first_ambiguous = ambiguity
                    continue
                resolve_file = getattr(provider, "resolve_movie_file", None)
                suggestion = resolve_file(path) if callable(resolve_file) else None
                if suggestion is not None:
                    return MetadataResolution(suggestion, False, "", ambiguity.candidate_count)
            return first_ambiguous or MetadataResolution(None, False, "Kein passender Film-Treffer gefunden.", 0)
        suggestion = client.resolve_movie_file(path)
        return MetadataResolution(suggestion, False, "", 1 if suggestion is not None else 0)

    def resolve_movie_file(self, path: str):
        return self.resolve_movie(path, require_unambiguous=False).suggestion
