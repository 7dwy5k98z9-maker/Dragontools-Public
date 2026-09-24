# -*- coding: utf-8 -*-
"""Retry policy for transient online-metadata provider failures."""
from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from typing import TypeVar

from .online_metadata_types import OnlineMetadataError

_LOG = logging.getLogger(__name__)
_T = TypeVar("_T")

MAX_METADATA_ATTEMPTS = 3
INITIAL_BACKOFF_S = 0.5
MAX_BACKOFF_S = 2.0
MAX_RETRY_AFTER_S = 10.0
JITTER_MAX_S = 0.2


class RetryableOnlineMetadataError(OnlineMetadataError):
    """Transient provider/network failure that may succeed on a later attempt."""

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after if retry_after is None else max(0.0, float(retry_after))


def retry_online_metadata_call(
    operation: Callable[[], _T],
    *,
    provider: str,
    attempts: int = MAX_METADATA_ATTEMPTS,
) -> _T:
    """Execute one provider operation with bounded exponential backoff.

    Only explicitly transient failures are retried. Authentication/configuration
    errors and ordinary provider errors fail immediately.
    """
    total_attempts = max(1, int(attempts))
    last_error: RetryableOnlineMetadataError | None = None

    for attempt in range(1, total_attempts + 1):
        try:
            return operation()
        except RetryableOnlineMetadataError as exc:
            last_error = exc
            if attempt >= total_attempts:
                break
            delay = _retry_delay(exc, retry_number=attempt)
            _LOG.warning(
                "%s temporary metadata failure (attempt %d/%d): %s; retry in %.2fs",
                provider,
                attempt,
                total_attempts,
                exc,
                delay,
            )
            time.sleep(delay)

    if last_error is None:
        raise OnlineMetadataError(f"{provider}: Metadaten-Abfrage ohne Ergebnis beendet.")
    raise OnlineMetadataError(
        f"{last_error} (nach {total_attempts} Versuchen)"
    ) from last_error


def _retry_delay(error: RetryableOnlineMetadataError, *, retry_number: int) -> float:
    backoff = min(INITIAL_BACKOFF_S * (2 ** max(0, retry_number - 1)), MAX_BACKOFF_S)
    jitter = random.uniform(0.0, JITTER_MAX_S)
    delay = backoff + jitter
    if error.retry_after is not None:
        delay = max(delay, min(float(error.retry_after), MAX_RETRY_AFTER_S))
    return min(delay, MAX_RETRY_AFTER_S)
