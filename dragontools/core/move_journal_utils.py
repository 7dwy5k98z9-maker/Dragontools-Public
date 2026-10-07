# -*- coding: utf-8 -*-
from __future__ import annotations
import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any
from .move_journal_contracts import RETRYABLE

_LOG = logging.getLogger(__name__)

def _read_json_dict(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _LOG.warning("Move-Journal konnte nicht gelesen werden: %s (%s)", path, exc)
        return {}
    return data if isinstance(data, dict) else {}

def _remove_path(path: Path) -> None:
    """Entfernt Datei, Symlink oder Verzeichnis fuer Recovery-Cleanup."""
    if path.is_symlink() or not path.is_dir():
        path.unlink(missing_ok=True)
    else:
        shutil.rmtree(path)

def _normalize_status(status: Any) -> str:
    text = str(status or "").strip().lower()
    if text in {"success", "done"}:
        return "ok"
    if text in {"failed", "fail"}:
        return "error"
    if text == "warning":
        return "warn"
    return text or "unknown"

def _has_retryable_files(data: dict[str, Any]) -> bool:
    files = data.get("files") if isinstance(data.get("files"), dict) else {}
    for row in files.values():
        item = row if isinstance(row, dict) else {}
        if _normalize_status(item.get("status")) in RETRYABLE:
            return True
    return False

def _json_safe_dict(value: dict) -> dict:
    # Planned targets are authoritative. Never silently drop their whole map.
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False,
        default=lambda item: os.fspath(item) if isinstance(item, os.PathLike) else _invalid_context(item)))

def _invalid_context(item):
    raise TypeError(f'Nicht serialisierbarer Move-Kontext: {type(item).__name__}')

def _dedupe(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for path in paths:
        key = os.path.normcase(str(path))
        if key in seen:
            continue
        seen.add(key)
        out.append(str(path))
    return out

def _unique_archive_path(path: Path) -> Path:
    if not path.exists():
        return path
    for idx in range(2, 10_000):
        candidate = path.with_name(f"{path.stem}_{idx}{path.suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{path.stem}_{datetime.now().strftime('%H%M%S')}{path.suffix}")

def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def resume_companion_proofs(planned):
    """Carry verified companion records into a new, independently owned run."""
    proofs = planned.get('resume_companion_proofs') if isinstance(planned, dict) else None
    return _json_safe_dict(proofs) if isinstance(proofs, dict) else {}
