from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class JellyfinAuxMetadata:
    providers_by_item: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    values_by_item: dict[str, list[tuple[str, str, int]]] = field(default_factory=dict)
    people_by_item: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    collections: dict[str, str] = field(default_factory=dict)
    collection_members: dict[str, list[tuple[str, int]]] = field(default_factory=dict)


def key(value: Any) -> str:
    return str(value or "").strip().casefold()


def actual(columns: dict[str, str], *names: str) -> str | None:
    for name in names:
        col = columns.get(name.casefold())
        if col:
            return col
    return None


__all__ = ["JellyfinAuxMetadata", "key", "actual"]
