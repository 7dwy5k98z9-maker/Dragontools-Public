# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request

from .online_metadata_cache import read_metadata_cache, write_metadata_cache
from .online_metadata_common import (
    TVDB_API_BASE,
    TVDB_TIMEOUT_S,
    OnlineMetadataAuthError,
)
from .online_metadata_http import request_json
from .online_metadata_retry import retry_online_metadata_call
from .version import APP_VERSION

class TvdbTransportMixin:
    def enable_fresh_session(self) -> None:
        with self._request_cache_lock:
            self._fresh_session_enabled = True
            self._request_session_cache.clear()

    def _request_json(
        self,
        endpoint: str,
        params: dict[str, Any],
        *,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        clean_params = {str(k): str(v) for k, v in params.items() if v not in (None, "")}
        cache_key = self._cache_key(endpoint, clean_params)
        with self._request_cache_lock:
            session_value = self._request_session_cache.get(cache_key)
            if session_value is not None and not force_refresh:
                return session_value

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

        # Login only after all usable caches missed.
        token = self._auth_token()
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": f"DragonTools/{APP_VERSION}",
        }
        query = urlencode(clean_params)
        url = f"{TVDB_API_BASE}{endpoint}"
        if query:
            url = f"{url}?{query}"
        data = retry_online_metadata_call(
            lambda: self._http_get(url, headers, TVDB_TIMEOUT_S),
            provider="TheTVDB",
        )
        write_metadata_cache(
            self.cache_dir,
            cache_key,
            data,
            enabled=self.config.cache_enabled,
        )
        with self._request_cache_lock:
            self._request_session_cache[cache_key] = data
        return data

    def _auth_token(self) -> str:
        if self._token:
            return self._token
        # Shared NFO clients must not race multiple /login calls.
        with self._auth_lock:
            if self._token:
                return self._token
            payload: dict[str, Any] = {"apikey": self.config.tvdb_api_key}
            if self.config.tvdb_pin:
                payload["pin"] = self.config.tvdb_pin
            data = retry_online_metadata_call(
                lambda: self._http_post(
                    f"{TVDB_API_BASE}/login",
                    {
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "User-Agent": f"DragonTools/{APP_VERSION}",
                    },
                    payload,
                    TVDB_TIMEOUT_S,
                ),
                provider="TheTVDB-Login",
            )
            token = str(
                ((data.get("data") or {}) if isinstance(data, dict) else {}).get("token")
                or ""
            ).strip()
            if not token:
                raise OnlineMetadataAuthError("TheTVDB lieferte kein gültiges Bearer-Token.")
            self._token = token
            return token

    def _cache_key(self, endpoint: str, params: dict[str, str]) -> str:
        raw = json.dumps({"endpoint": endpoint, "params": params}, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _urllib_get(self, url: str, headers: dict[str, str], timeout: int) -> dict[str, Any]:
        request = Request(url, headers=headers, method="GET")
        return request_json(
            request,
            timeout,
            label="TheTVDB",
            auth_error_template="TheTVDB lehnt die Anmeldung ab (HTTP {code}).",
        )

    def _urllib_post(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout: int,
    ) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = Request(url, data=body, headers=headers, method="POST")
        return request_json(
            request,
            timeout,
            label="TheTVDB-Login",
            auth_error_template="TheTVDB-Zugangsdaten wurden abgelehnt (HTTP {code}).",
        )
