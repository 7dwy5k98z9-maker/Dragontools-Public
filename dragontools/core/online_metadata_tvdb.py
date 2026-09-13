# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Any, Callable

from .online_metadata_common import (
    OnlineMetadataAuthError,
    OnlineMetadataConfig,
    ParsedMetadataResolverMixin,
    default_metadata_cache_dir,
)
from .online_metadata_tvdb_episode_data import TvdbEpisodeDataMixin
from .online_metadata_tvdb_resolver import TvdbResolverMixin
from .online_metadata_tvdb_suggestions import TvdbSuggestionMixin
from .online_metadata_tvdb_transport import TvdbTransportMixin

class TheTvdbClient(TvdbResolverMixin, TvdbSuggestionMixin, TvdbEpisodeDataMixin, TvdbTransportMixin, ParsedMetadataResolverMixin):
    def __init__(
        self,
        config: OnlineMetadataConfig,
        *,
        cache_dir: str | Path | None = None,
        http_get: Callable[[str, dict[str, str], int], dict[str, Any]] | None = None,
        http_post: Callable[[str, dict[str, str], dict[str, Any], int], dict[str, Any]] | None = None,
    ) -> None:
        if not config.has_tvdb_credentials:
            raise OnlineMetadataAuthError("Kein TheTVDB API-Key, PIN oder Bearer-Token hinterlegt.")
        self.config = config
        self.cache_dir = Path(cache_dir) if cache_dir is not None else default_metadata_cache_dir(provider="thetvdb")
        self._http_get = http_get or self._urllib_get
        self._http_post = http_post or self._urllib_post
        self._token = config.tvdb_bearer_token.strip()
        # Per-client batch cache: one fresh episode-list request is enough for
        # all episodes of the same series during one renamer/NFO run.
        self._episode_batch_cache: dict[tuple[int, str, str], list[dict[str, Any]]] = {}
        self._episode_batch_fresh: set[tuple[int, str, str]] = set()
        self._series_details_batch_cache: dict[tuple[int, bool], dict[str, Any]] = {}
        self._series_details_batch_fresh: set[tuple[int, bool]] = set()
        self._episode_batch_lock = RLock()
        self._auth_lock = RLock()
        self._request_cache_lock = RLock()
        self._request_session_cache: dict[str, dict[str, Any]] = {}
        self._fresh_session_enabled = False
        self.provider_label = "TheTVDB"
