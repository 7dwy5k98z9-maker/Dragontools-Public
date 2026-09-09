# -*- coding: utf-8 -*-
"""Gemeinsamer JSON-Dateicache für Online-Metadatenprovider."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def read_metadata_cache(
    cache_dir: Path,
    cache_key: str,
    *,
    enabled: bool,
    cache_days: int,
) -> dict[str, Any] | None:
    """Liest einen gültigen Cache-Eintrag oder gibt ``None`` zurück."""
    if not enabled:
        return None
    cache_file = cache_dir / f"{cache_key}.json"
    if not cache_file.exists():
        return None
    try:
        payload = json.loads(cache_file.read_text(encoding="utf-8"))
        created = float(payload.get("created") or 0)
        max_age = max(1, int(cache_days)) * 86400
        if time.time() - created > max_age:
            return None
        data = payload.get("data")
        return data if isinstance(data, dict) else None
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
        return None


def write_metadata_cache(
    cache_dir: Path,
    cache_key: str,
    data: dict[str, Any],
    *,
    enabled: bool,
) -> None:
    """Schreibt einen Cache-Eintrag best-effort; Cache-I/O ist nicht fatal."""
    if not enabled:
        return
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        payload = {"created": time.time(), "data": data}
        (cache_dir / f"{cache_key}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


__all__ = ["read_metadata_cache", "write_metadata_cache"]
