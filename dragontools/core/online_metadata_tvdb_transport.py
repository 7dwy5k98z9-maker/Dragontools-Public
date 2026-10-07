# -*- coding: utf-8 -*-
from __future__ import annotations

from copy import deepcopy
import hashlib
import logging
import json
from threading import RLock
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request

from .online_metadata_cache import read_metadata_cache, write_metadata_cache, reset_metadata_session
from .online_metadata_common import (
    TVDB_API_BASE,
    TVDB_TIMEOUT_S,
    OnlineMetadataAuthError,
)
from .online_metadata_http import request_json
from .online_metadata_retry import retry_online_metadata_call
from .online_metadata_types import OnlineMetadataResponseError
from .version import APP_VERSION

_LOG = logging.getLogger(__name__)
# Serializes login/refresh across multiple TheTvdbClient instances in one process.
_TVDB_AUTH_REFRESH_LOCK = RLock()


class TvdbTransportMixin:
    def enable_fresh_session(self) -> None:
        reset_metadata_session(self, '_episode_batch_lock', ('_renamer_search_cache', '_episode_batch_cache', '_episode_batch_fresh', '_series_details_batch_cache', '_series_details_batch_fresh'))

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
                try:
                    self._validate_tvdb_payload(endpoint, session_value)
                except OnlineMetadataResponseError:
                    self._request_session_cache.pop(cache_key, None)
                else:
                    return deepcopy(session_value)

        if not force_refresh and not self._fresh_session_enabled:
            cached = read_metadata_cache(
                self.cache_dir,
                cache_key,
                enabled=self.config.cache_enabled,
                cache_days=self.config.cache_days,
            )
            if cached is not None:
                try:
                    self._validate_tvdb_payload(endpoint, cached)
                except OnlineMetadataResponseError:
                    cached = None
                if cached is not None:
                    with self._request_cache_lock:
                        self._request_session_cache[cache_key] = deepcopy(cached)
                    return deepcopy(cached)

        # Login only after all usable caches missed.  A TVDB bearer token is
        # finite-lived; if an already-cached token is rejected and reusable API
        # credentials are available, refresh it exactly once.  Never loop on
        # genuinely invalid login credentials.
        query = urlencode(clean_params)
        url = f"{TVDB_API_BASE}{endpoint}"
        if query:
            url = f"{url}?{query}"

        def authorized_get(token: str) -> dict[str, Any]:
            headers = {
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
                "User-Agent": f"DragonTools/{APP_VERSION}",
            }
            return retry_online_metadata_call(
                lambda: self._http_get(url, headers, TVDB_TIMEOUT_S),
                provider="TheTVDB",
            )

        token = self._auth_token()
        try:
            data = authorized_get(token)
        except OnlineMetadataAuthError:
            if not self.config.tvdb_api_key.strip():
                raise
            refreshed_token = self._refresh_after_auth_failure(token)
            data = authorized_get(refreshed_token)

        self._validate_tvdb_payload(endpoint, data)
        write_metadata_cache(
            self.cache_dir,
            cache_key,
            data,
            enabled=self.config.cache_enabled,
        )
        with self._request_cache_lock:
            self._request_session_cache[cache_key] = deepcopy(data)
        return deepcopy(data)

    @staticmethod
    def _validate_tvdb_payload(endpoint: str, data: Any) -> None:
        if not isinstance(data, dict):
            raise OnlineMetadataResponseError(
                f"TheTVDB-Antwort hat ein unerwartetes JSON-Format "
                f"({type(data).__name__} statt Objekt)."
            )
        payload = data.get("data")
        if endpoint == "/search":
            if not isinstance(payload, (list, dict)):
                raise OnlineMetadataResponseError(
                    "TheTVDB-Suchantwort enthält keine gültigen Daten."
                )
        elif "/episodes/" in endpoint:
            valid = isinstance(payload, list)
            if isinstance(payload, dict):
                nested = payload.get("episodes") if "episodes" in payload else payload.get("data")
                valid = isinstance(nested, list)
            if not valid:
                raise OnlineMetadataResponseError(
                    "TheTVDB-Episodenantwort enthält keine gültige Episodenliste."
                )
        elif endpoint.endswith("/extended"):
            if not isinstance(payload, dict):
                raise OnlineMetadataResponseError(
                    f"TheTVDB-Detailantwort für {endpoint} enthält keinen Datensatz."
                )
            if payload.get("id") is None and payload.get("tvdb_id") is None and payload.get("tvdbId") is None:
                raise OnlineMetadataResponseError(
                    f"TheTVDB-Detailantwort für {endpoint} enthält keine ID."
                )

    def _auth_token(self) -> str:
        if self._token:
            return self._token
        # Shared clients must not race multiple /login calls. The process-wide
        # lock also lets a second client reuse a token refreshed moments ago by
        # the first one.
        with _TVDB_AUTH_REFRESH_LOCK:
            with self._auth_lock:
                if self._token:
                    return self._token
                persisted = self._load_persisted_bearer_token()
                if persisted:
                    self._token = persisted
                    return persisted
                return self._login_new_token()

    def _refresh_after_auth_failure(self, failed_token: str) -> str:
        """Invalidate only the rejected token, then reuse or issue one fresh token."""
        with _TVDB_AUTH_REFRESH_LOCK:
            with self._auth_lock:
                if self._token and self._token != failed_token:
                    return self._token

                persisted = self._load_persisted_bearer_token()
                if persisted and persisted != failed_token:
                    self._token = persisted
                    return persisted

                self._token = ""
                if persisted == failed_token:
                    # Make the invalidation durable so later clients do not start
                    # with a token that the provider has already rejected.
                    self._persist_bearer_token("")
                return self._login_new_token()

    def _login_new_token(self) -> str:
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
        record = data.get("data") if isinstance(data, dict) else None
        raw_token = record.get("token") if isinstance(record, dict) else None
        token = raw_token.strip() if isinstance(raw_token, str) else ""
        if not token or any(ord(ch) < 33 or ord(ch) > 126 for ch in token):
            raise OnlineMetadataAuthError("TheTVDB lieferte kein gültiges Bearer-Token.")
        self._token = token
        self._persist_bearer_token(token)
        return token

    def _load_persisted_bearer_token(self) -> str:
        loader = getattr(self.config, "tvdb_bearer_token_load", None)
        if not callable(loader):
            return ""
        try:
            return str(loader() or "").strip()
        except Exception:
            _LOG.warning(
                "TheTVDB Bearer-Token konnte nicht aus den Einstellungen nachgeladen werden.",
                exc_info=True,
            )
            return ""

    def _persist_bearer_token(self, token: str) -> None:
        """Persist an automatically managed bearer without breaking the request.

        Authentication itself is the primary operation. If the settings store
        is temporarily unavailable (for example a locked profile), keep the
        freshly issued token in memory and log the persistence failure instead
        of turning a successful TVDB login into a metadata failure.
        """
        store = getattr(self.config, "tvdb_bearer_token_store", None)
        if not callable(store):
            return
        try:
            store(str(token or "").strip())
        except Exception:
            _LOG.warning(
                "TheTVDB Bearer-Token konnte nicht dauerhaft gespeichert werden.",
                exc_info=True,
            )

    def _cache_key(self, endpoint: str, params: dict[str, str]) -> str:
        raw = json.dumps({"provider": "thetvdb", "endpoint": endpoint, "params": params}, sort_keys=True)
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
