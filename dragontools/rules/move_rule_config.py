# -*- coding: utf-8 -*-
"""Migration und Defaults der Move-Regeln."""
from __future__ import annotations

from typing import Any
from ..core.config_migration import SCHEMA_VERSION_KEY, finish_migration

_DEFAULT_MOVE_RULES: dict[str, Any] = {
    SCHEMA_VERSION_KEY: 1,
    "series_patterns": [
        r"(?i)s\s*(?P<season>\d{1,4})[.\-_\s]*e\s*(?P<episode>\d{1,4})",
        r"(?i)s\s*(?P<season>\d{1,4})\s*e\s*(?P<episode>\d{1,4})(?:[e\-]e?\d{1,4})*",
        r"(?i)(?P<season>\d{1,4})x(?P<episode>\d{1,4})",
    ],
    "series_test_examples": [
        "Show.S01E01.mkv",
        "Show.S01E01E02.mkv",
        "Show.S01E01-E02.mkv",
        "Show.1x01.mkv",
    ],
    "anime_keywords": ["BD", "BluRay", "BDRip", "WEBRip", "[SubGroup]"],
    "collection_rules": [],
    "folder_structure": {
        "series": "{tv_root}/{series_name}/Staffel {season:02d}/",
        "movie": "{film_root}/{title} ({year})/",
        "anime": "{anime_root}/{series_name}/Staffel {season:02d}/",
    },
}


def migrate_move_rules(
    rules: dict[str, Any] | None,
    *,
    source_path: str | None = None,
    reporter: Any = None,
) -> dict[str, Any]:
    raw = dict(rules or {})
    migrated = dict(raw)
    messages: list[str] = []

    for key, default_value in _DEFAULT_MOVE_RULES.items():
        if key == SCHEMA_VERSION_KEY:
            continue
        if key not in migrated:
            migrated[key] = default_value
            messages.append(f"Move-Regel '{key}' ergänzt")

    folder_structure = dict(_DEFAULT_MOVE_RULES["folder_structure"])
    if isinstance(raw.get("folder_structure"), dict):
        folder_structure.update(raw["folder_structure"])
    else:
        messages.append("Move-Ordnerstruktur ergänzt")
    migrated["folder_structure"] = folder_structure

    return finish_migration(
        "move_rules",
        migrated,
        raw=raw,
        messages=messages,
        source_path=source_path,
        reporter=reporter,
    ).data
