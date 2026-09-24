# -*- coding: utf-8 -*-
"""Low-level urllib error classification for metadata providers."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .online_metadata_retry import RetryableOnlineMetadataError
from .online_metadata_types import OnlineMetadataAuthError, OnlineMetadataError

_RETRYABLE_HTTP_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


def request_json(
    request: Request,
    timeout: int,
    *,
    label: str,
    auth_error_template: str | None = None,
) -> dict[str, Any]:
    """Open one JSON request and classify permanent vs. transient failures."""
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code in (401, 403) and auth_error_template:
            raise OnlineMetadataAuthError(auth_error_template.format(code=exc.code)) from exc
        detail = _http_error_detail(exc)
        message = f"{label} meldet HTTP {exc.code}{detail}"
        if exc.code in _RETRYABLE_HTTP_STATUS:
            raise RetryableOnlineMetadataError(
                message,
                retry_after=_retry_after_seconds(exc.headers.get("Retry-After") if exc.headers else None),
            ) from exc
        raise OnlineMetadataError(message) from exc
    except URLError as exc:
        raise RetryableOnlineMetadataError(
            f"{label} ist nicht erreichbar: {exc.reason}"
        ) from exc
    except TimeoutError as exc:
        raise RetryableOnlineMetadataError(
            f"{label}-Abfrage hat zu lange gedauert."
        ) from exc
    except json.JSONDecodeError as exc:
        raise RetryableOnlineMetadataError(
            f"{label}-Antwort war kein gültiges JSON."
        ) from exc


def _http_error_detail(exc: HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", errors="replace")
    except Exception:
        return ""
    return f" ({body[:200]})" if body else ""


def _retry_after_seconds(value: str | None) -> float | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        target = parsedate_to_datetime(raw)
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        return max(0.0, (target - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None
