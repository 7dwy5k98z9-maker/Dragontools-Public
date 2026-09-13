# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .online_metadata_cache import read_metadata_cache, write_metadata_cache
from .online_metadata_common import (
    TVDB_API_BASE,
    TVDB_TIMEOUT_S,
    OnlineMetadataAuthError,
    OnlineMetadataError,
)
from .settings import APP_VERSION

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
        data = self._http_get(url, headers, TVDB_TIMEOUT_S)
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
            data = self._http_post(
                f"{TVDB_API_BASE}/login",
                {
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "User-Agent": f"DragonTools/{APP_VERSION}",
                },
                payload,
                TVDB_TIMEOUT_S,
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
            if exc.code in (401, 403):
                raise OnlineMetadataAuthError(f"TheTVDB lehnt die Anmeldung ab (HTTP {exc.code}).") from exc
            raise OnlineMetadataError(f"TheTVDB meldet HTTP {exc.code}{detail}") from exc
        except URLError as exc:
            raise OnlineMetadataError(f"TheTVDB ist nicht erreichbar: {exc.reason}") from exc
        except TimeoutError as exc:
            raise OnlineMetadataError("TheTVDB-Abfrage hat zu lange gedauert.") from exc
        except json.JSONDecodeError as exc:
            raise OnlineMetadataError("TheTVDB-Antwort war kein gültiges JSON.") from exc

    def _urllib_post(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout: int,
    ) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = Request(url, data=body, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise OnlineMetadataAuthError(f"TheTVDB-Zugangsdaten wurden abgelehnt (HTTP {exc.code}).") from exc
            raise OnlineMetadataError(f"TheTVDB-Login meldet HTTP {exc.code}.") from exc
        except URLError as exc:
            raise OnlineMetadataError(f"TheTVDB-Login ist nicht erreichbar: {exc.reason}") from exc
        except TimeoutError as exc:
            raise OnlineMetadataError("TheTVDB-Login hat zu lange gedauert.") from exc
        except json.JSONDecodeError as exc:
            raise OnlineMetadataError("TheTVDB-Login-Antwort war kein gültiges JSON.") from exc
