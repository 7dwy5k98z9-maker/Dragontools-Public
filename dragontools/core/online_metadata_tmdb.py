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
from .online_metadata_tmdb_resolver import TmdbResolverMixin
from .online_metadata_tmdb_suggestions import TmdbSuggestionMixin
from .online_metadata_tmdb_transport import TmdbTransportMixin


class TmdbClient(
    TmdbResolverMixin,
    TmdbSuggestionMixin,
    TmdbTransportMixin,
    ParsedMetadataResolverMixin,
):
    """TMDB client facade composed from focused resolver/transport mixins."""

    def __init__(
        self,
        config: OnlineMetadataConfig,
        *,
        cache_dir: str | Path | None = None,
        http_get: Callable[[str, dict[str, str], int], dict[str, Any]] | None = None,
    ) -> None:
        if not config.has_tmdb_credentials:
            raise OnlineMetadataAuthError("Kein TMDB API-Key oder Read-Access-Token hinterlegt.")
        self.config = config
        self.cache_dir = (
            Path(cache_dir)
            if cache_dir is not None
            else default_metadata_cache_dir(provider="tmdb")
        )
        self._http_get = http_get or self._urllib_get
        self._request_cache_lock = RLock()
        self._request_session_cache: dict[str, dict[str, Any]] = {}
        self._fresh_session_enabled = False
        self.provider_label = "TMDB"
