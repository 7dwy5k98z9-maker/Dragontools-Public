# -*- coding: utf-8 -*-
"""Small Jellyfin HTTP client used by the optional API integration."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .version import APP_VERSION

_TRANSIENT_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})
_DEFAULT_BACKOFF_SECONDS = (0.5, 1.0)
_MAX_RETRY_AFTER_SECONDS = 10.0


class JellyfinApiError(RuntimeError):
    """Raised when a Jellyfin API operation cannot be completed safely."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class JellyfinServerInfo:
    server_name: str
    version: str
    operating_system: str = ""


def normalize_server_url(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise JellyfinApiError("Jellyfin-Serveradresse fehlt.")
    if "://" not in text:
        text = "http://" + text
    if not text.lower().startswith(("http://", "https://")):
        raise JellyfinApiError("Jellyfin-Serveradresse muss HTTP oder HTTPS verwenden.")
    return text.rstrip("/")


def _authorization_header(api_key: str) -> str:
    token = str(api_key or "").strip()
    if not token:
        raise JellyfinApiError("Jellyfin-API-Key fehlt.")
    safe_token = token.replace('"', "")
    return (
        'MediaBrowser Client="Dragon Tools", Device="Dragon Tools", '
        f'DeviceId="dragontools", Version="{APP_VERSION}", Token="{safe_token}"'
    )


def _retry_after_seconds(value: str | None, *, now: Callable[[], datetime]) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return max(0.0, float(text))
    except ValueError:
        pass
    try:
        target = parsedate_to_datetime(text)
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        return max(0.0, (target - now()).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


class JellyfinClient:
    """Minimal synchronous Jellyfin API client with bounded transient retries."""

    def __init__(
        self,
        server_url: str,
        api_key: str,
        *,
        timeout: float = 8.0,
        max_attempts: int = 3,
        opener: Callable = urlopen,
        sleeper: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.server_url = normalize_server_url(server_url)
        self.api_key = str(api_key or "").strip()
        _authorization_header(self.api_key)
        self.timeout = max(1.0, float(timeout))
        self.max_attempts = max(1, int(max_attempts))
        self._opener = opener
        self._sleeper = sleeper
        self._now = now or (lambda: datetime.now(timezone.utc))

    def get_system_info(self) -> JellyfinServerInfo:
        payload = self._request_json("GET", "/System/Info")
        if not isinstance(payload, dict):
            raise JellyfinApiError("Jellyfin lieferte unerwartete Systeminformationen.")
        return JellyfinServerInfo(
            server_name=str(payload.get("ServerName") or payload.get("Name") or "Jellyfin"),
            version=str(payload.get("Version") or "unbekannt"),
            operating_system=str(payload.get("OperatingSystem") or ""),
        )

    def get_physical_paths(self) -> list[str]:
        """Return the media roots exactly as Jellyfin sees them.

        Targeted refreshes must use paths from Jellyfin's filesystem namespace
        (for example ``/TVSerien`` inside Docker), not the Windows/UNC paths
        Dragon Tools used to move the file.
        """
        payload = self._request_json("GET", "/Library/PhysicalPaths")
        if not isinstance(payload, list):
            raise JellyfinApiError("Jellyfin lieferte unerwartete Mediathekspfade.")

        result: list[str] = []
        seen: set[str] = set()
        for raw in payload:
            path = str(raw or "").strip()
            if not path:
                continue
            key = path.replace("\\", "/").rstrip("/").casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append(path)
        if not result:
            raise JellyfinApiError("Jellyfin meldet keine physischen Mediathekspfade.")
        return result

    def notify_media_updates(self, updates: Iterable[dict[str, str]]) -> None:
        cleaned: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for raw in updates:
            path = str(raw.get("Path") or "").strip()
            update_type = str(raw.get("UpdateType") or "").strip().title()
            if not path or update_type not in {"Created", "Modified", "Deleted"}:
                continue
            key = (path.casefold(), update_type)
            if key in seen:
                continue
            seen.add(key)
            cleaned.append({"Path": path, "UpdateType": update_type})
        if not cleaned:
            return
        self._request(
            "POST",
            "/Library/Media/Updated",
            payload={"Updates": cleaned},
            expect_json=False,
        )

    def get_scheduled_tasks(self) -> list[dict]:
        payload = self._request_json("GET", "/ScheduledTasks")
        if not isinstance(payload, list):
            raise JellyfinApiError("Jellyfin lieferte unerwartete Scheduled-Task-Daten.")
        return [dict(item) for item in payload if isinstance(item, dict)]

    def is_library_scan_running(self) -> bool:
        """Return whether Jellyfin's global media-library scan is active."""
        for task in self.get_scheduled_tasks():
            key = str(task.get("Key") or "").strip().casefold()
            name = str(task.get("Name") or "").strip().casefold()
            state = str(task.get("State") or "").strip().casefold()
            is_library_scan = (
                "refreshmedialibrary" in key
                or key in {"refreshlibrary", "scanlibrary"}
                or ("scan" in name and "library" in name)
                or ("medien-bibliothek" in name and "scann" in name)
            )
            if is_library_scan and state in {"running", "cancelling"}:
                return True
        return False

    def refresh_library(self) -> None:
        self._request("POST", "/Library/Refresh", expect_json=False)

    def _request_json(self, method: str, endpoint: str, *, payload: dict | None = None):
        return self._request(method, endpoint, payload=payload, expect_json=True)

    def _request(self, method: str, endpoint: str, *, payload: dict | None = None, expect_json: bool):
        url = self.server_url + "/" + endpoint.lstrip("/")
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "Authorization": _authorization_header(self.api_key),
            "User-Agent": f"DragonTools/{APP_VERSION}",
        }
        if body is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"

        last_error: JellyfinApiError | None = None
        for attempt in range(1, self.max_attempts + 1):
            request = Request(url, data=body, headers=headers, method=method.upper())
            try:
                with self._opener(request, timeout=self.timeout) as response:
                    raw = response.read()
                if not expect_json:
                    return None
                if not raw:
                    raise JellyfinApiError("Jellyfin lieferte eine leere JSON-Antwort.")
                try:
                    return json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    last_error = JellyfinApiError(f"Ungültige JSON-Antwort von Jellyfin: {exc}")
                    if attempt >= self.max_attempts:
                        raise last_error from exc
            except HTTPError as exc:
                status = int(getattr(exc, "code", 0) or 0)
                if status not in _TRANSIENT_STATUS_CODES or attempt >= self.max_attempts:
                    raise JellyfinApiError(self._http_error_message(status), status_code=status) from exc
                last_error = JellyfinApiError(self._http_error_message(status), status_code=status)
                retry_after = _retry_after_seconds(exc.headers.get("Retry-After"), now=self._now)
                self._sleep_before_retry(attempt, retry_after=retry_after)
                continue
            except (URLError, TimeoutError, ConnectionError, OSError) as exc:
                last_error = JellyfinApiError(f"Jellyfin ist nicht erreichbar: {exc}")
                if attempt >= self.max_attempts:
                    raise last_error from exc
                self._sleep_before_retry(attempt)
                continue

            if attempt < self.max_attempts:
                self._sleep_before_retry(attempt)

        raise last_error or JellyfinApiError("Jellyfin-Anfrage ist fehlgeschlagen.")

    def _sleep_before_retry(self, attempt: int, *, retry_after: float | None = None) -> None:
        if retry_after is not None:
            delay = min(max(0.0, float(retry_after)), _MAX_RETRY_AFTER_SECONDS)
        else:
            index = min(max(0, attempt - 1), len(_DEFAULT_BACKOFF_SECONDS) - 1)
            delay = _DEFAULT_BACKOFF_SECONDS[index]
        self._sleeper(max(0.0, float(delay)))

    @staticmethod
    def _http_error_message(status: int) -> str:
        if status in {401, 403}:
            return f"Jellyfin hat den API-Zugriff verweigert (HTTP {status}). API-Key/Berechtigung prüfen."
        if status == 404:
            return "Jellyfin-Endpunkt wurde nicht gefunden (HTTP 404). Serveradresse/Base-URL prüfen."
        if status == 429:
            return "Jellyfin begrenzt aktuell API-Anfragen (HTTP 429)."
        if status:
            return f"Jellyfin-API antwortete mit HTTP {status}."
        return "Jellyfin-API-Anfrage ist fehlgeschlagen."
