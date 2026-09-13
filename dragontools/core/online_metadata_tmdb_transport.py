# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .online_metadata_cache import read_metadata_cache, write_metadata_cache
from .online_metadata_common import TMDB_API_BASE, TMDB_TIMEOUT_S, OnlineMetadataError
from .settings import APP_VERSION


class TmdbTransportMixin:
    def enable_fresh_session(self) -> None:
        """Bypass the persistent cache once per request for this client session."""
        with self._request_cache_lock:
            self._fresh_session_enabled = True
            self._request_session_cache.clear()

    """HTTP, authentication and cache plumbing for the TMDB client."""

    def _request_json(
        self,
        endpoint: str,
        params: dict[str, Any],
        *,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        clean_params = {
            str(key): str(value)
            for key, value in params.items()
            if value not in (None, "")
        }
        headers = {
            "Accept": "application/json",
            "User-Agent": f"DragonTools/{APP_VERSION}",
        }
        if self.config.tmdb_read_token:
            headers["Authorization"] = f"Bearer {self.config.tmdb_read_token}"
        else:
            clean_params["api_key"] = self.config.tmdb_api_key

        cache_key = self._cache_key(endpoint, clean_params)
        with self._request_cache_lock:
            session_value = self._request_session_cache.get(cache_key)
            if session_value is not None and not force_refresh:
                return session_value

        # A final rename/NFO metadata session must see current provider data.
        # It therefore ignores the persistent multi-day cache on the first
        # request, while still reusing the live response within this batch.
        if not force_refresh and not self._fresh_session_enabled:
            cached = read_metadata_cache(
                self.cache_dir,
                cache_key,
                enabled=self.config.cache_enabled,
                cache_days=self.config.cache_days,
            )
            if cached is not None:
                with self._request_cache_lock:
                    self._request_session_cache[cache_key] = cached
                return cached

        query = urlencode(clean_params)
        url = f"{TMDB_API_BASE}{endpoint}"
        if query:
            url = f"{url}?{query}"
        data = self._http_get(url, headers, TMDB_TIMEOUT_S)
        write_metadata_cache(
            self.cache_dir,
            cache_key,
            data,
            enabled=self.config.cache_enabled,
        )
        with self._request_cache_lock:
            self._request_session_cache[cache_key] = data
        return data

    def _cache_key(self, endpoint: str, params: dict[str, str]) -> str:
        safe_params = {key: value for key, value in params.items() if key != "api_key"}
        raw = json.dumps({"endpoint": endpoint, "params": safe_params}, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _urllib_get(
        self,
        url: str,
        headers: dict[str, str],
        timeout: int,
    ) -> dict[str, Any]:
        request = Request(url, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = ""
            try:
                body = exc.read().decode("utf-8", errors="replace")
                detail = f" ({body[:200]})" if body else ""
            except Exception:
                pass
            raise OnlineMetadataError(f"TMDB meldet HTTP {exc.code}{detail}") from exc
        except URLError as exc:
            raise OnlineMetadataError(f"TMDB ist nicht erreichbar: {exc.reason}") from exc
        except TimeoutError as exc:
            raise OnlineMetadataError("TMDB-Abfrage hat zu lange gedauert.") from exc
        except json.JSONDecodeError as exc:
            raise OnlineMetadataError("TMDB-Antwort war kein gültiges JSON.") from exc
