# -*- coding: utf-8 -*-
"""Gemeinsamer JSON-Dateicache für Online-Metadatenprovider."""
from __future__ import annotations

import json
import math
import os
import tempfile
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
        if not isinstance(payload, dict):
            return None
        created = float(payload.get("created") or 0)
        age = time.time() - created
        if not math.isfinite(created) or age < 0:
            return None
        max_age = max(1, int(cache_days)) * 86400
        if age > max_age:
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
    temporary = None
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        payload = {"created": time.time(), "data": data}
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=cache_dir,
                prefix=f'.{cache_key}.', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, cache_dir / f'{cache_key}.json')
    except (OSError, TypeError, ValueError):
        pass
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def reset_metadata_session(client, batch_lock_name, cache_names):
    """Reset every layer while respecting the normal batch -> request lock order."""
    with getattr(client, batch_lock_name):
        with client._request_cache_lock:
            client._fresh_session_enabled = True
            client._request_session_cache.clear()
            for name in cache_names:
                getattr(client, name).clear()


__all__ = ["read_metadata_cache", "write_metadata_cache"]
