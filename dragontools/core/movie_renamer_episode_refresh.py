# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable

from .online_metadata_common import normalize_episode_metadata_title


_LOG = logging.getLogger(__name__)


def refresh_if_episode_title_fallback(
    client: Any,
    lookup: Path,
    results: Iterable[Any],
    episode: int,
) -> tuple[Any, ...]:
    resolved = tuple(results or ())
    refresh = getattr(client, "refresh_episode_candidates", None)
    if not resolved or not callable(refresh):
        return resolved
    if not contains_fallback_episode_title(resolved, episode):
        return resolved
    try:
        fresh = tuple(refresh(lookup, limit=6) or ())
    except Exception as exc:
        _LOG.warning(
            "Episoden-Metadaten konnten für %s nicht frisch geladen werden; "
            "der vorhandene Fallbacktitel bleibt aktiv: %s: %s",
            lookup.name,
            type(exc).__name__,
            exc,
        )
        return resolved
    if not fresh:
        _LOG.info(
            "Frische Episoden-Metadaten lieferten für %s keinen besseren Treffer; "
            "der vorhandene Fallbacktitel bleibt aktiv.",
            lookup.name,
        )
        return resolved
    return fresh


def contains_fallback_episode_title(results: Iterable[Any], episode: int) -> bool:
    for raw in results:
        if bool(getattr(raw, "title_is_fallback", False)):
            return True
        value = raw.get("episode_title") if isinstance(raw, dict) else getattr(raw, "title", "")
        if normalize_episode_metadata_title(value, episode)[1]:
            return True
    return False
