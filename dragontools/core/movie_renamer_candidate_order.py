# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any


def _sort_candidates(candidates: list[Any], *, client: Any | None) -> list[Any]:
    provider_order = tuple(getattr(client, "provider_order", ()) or ())
    rank = {str(provider).lower(): idx for idx, provider in enumerate(provider_order)}
    fallback_rank = len(rank)
    return sorted(
        candidates,
        key=lambda item: (
            0 if str(getattr(item, "match_reason", "") or "") == "Aliasregel" else 1,
            -float(getattr(item, "score", 0.0) or 0.0),
            rank.get(str(getattr(item, "provider", "") or "").lower(), fallback_rank),
            str(getattr(item, "series", getattr(item, "title", "")) or "").lower(),
        ),
    )


def _limit_candidates_with_provider_coverage(
    candidates: list[Any],
    *,
    client: Any | None,
    limit: int,
) -> list[Any]:
    per_provider_cap = max(1, int(limit))
    ordered = _sort_candidates(candidates, client=client)
    provider_order = tuple(
        str(provider or "").strip().lower()
        for provider in (getattr(client, "provider_order", ()) or ())
        if str(provider or "").strip()
    )
    if len(provider_order) < 2:
        return ordered[:per_provider_cap]

    counts: dict[str, int] = {}
    selected: list[Any] = []
    for item in ordered:
        provider = str(getattr(item, "provider", "") or "").strip().lower() or "metadata"
        if counts.get(provider, 0) >= per_provider_cap:
            continue
        selected.append(item)
        counts[provider] = counts.get(provider, 0) + 1
    return selected
