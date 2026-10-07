"""Keep catalog identity authoritative when refreshing technical media facts."""
from collections.abc import Mapping
from typing import Any


CATALOG_IDENTITY_FIELDS = frozenset({
    "item_type", "title", "original_title", "series_title", "season", "episode",
    "year", "source_id", "provider", "normalized_title",
})


def merge_analysis(item: dict[str, Any], analyzed: Mapping[str, Any]) -> None:
    """Refresh technical facts without replacing imported catalog identity."""
    item.update({key: value for key, value in analyzed.items() if key not in CATALOG_IDENTITY_FIELDS})


def preserve_catalog_identity(item: dict[str, Any], existing: Mapping[str, Any]) -> None:
    """Retain known catalog values; analysis supplies previously unknown ones."""
    for field in CATALOG_IDENTITY_FIELDS:
        if existing[field] is not None:
            item[field] = existing[field]
