# -*- coding: utf-8 -*-
"""Standardpfade und Aufräumen des Online-Metadaten-Caches."""
from __future__ import annotations

from pathlib import Path

from .paths import app_documents_dir
from .online_metadata_types import _metadata_provider_value


def default_metadata_cache_dir(root: str | Path | None = None, provider: str = "tmdb") -> Path:
    return app_documents_dir(root) / "MetadataCache" / _metadata_provider_value(provider, "tmdb")


def clear_default_metadata_cache(root: str | Path | None = None) -> int:
    base = app_documents_dir(root) / "MetadataCache"
    return _clear_cache_dir(base / "tmdb") + _clear_cache_dir(base / "thetvdb")


def _clear_cache_dir(cache_dir: Path) -> int:
    if not cache_dir.exists():
        return 0
    count = 0
    for file_path in cache_dir.glob("*.json"):
        try:
            file_path.unlink()
            count += 1
        except OSError:
            pass
    return count
