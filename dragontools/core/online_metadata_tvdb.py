# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .online_metadata_common import (
    OnlineMetadataAuthError,
    OnlineMetadataConfig,
    ParsedMetadataResolverMixin,
    default_metadata_cache_dir,
)
from .online_metadata_tvdb_resolver import TvdbResolverMixin
from .online_metadata_tvdb_suggestions import TvdbSuggestionMixin
from .online_metadata_tvdb_transport import TvdbTransportMixin

class TheTvdbClient(TvdbResolverMixin, TvdbSuggestionMixin, TvdbTransportMixin, ParsedMetadataResolverMixin):
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
        self.provider_label = "TheTVDB"
