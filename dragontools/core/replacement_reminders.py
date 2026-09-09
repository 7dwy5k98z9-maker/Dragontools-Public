from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .paths import app_documents_dir


REMINDER_DIRNAME = "Erinnerungen"
REMINDER_FILENAME = "episode_replacements.json"


def default_replacement_reminder_path(root: str | Path | None = None) -> Path:
    return app_documents_dir(root) / REMINDER_DIRNAME / REMINDER_FILENAME


def _now() -> datetime:
    return datetime.now()


def _timestamp(dt: datetime | None = None) -> str:
    return (dt or _now()).strftime("%Y-%m-%d %H:%M:%S")


def _id_prefix(dt: datetime | None = None) -> str:
    return (dt or _now()).strftime("#%Y%m%d-%H%M%S")


def _load(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(raw, dict):
        raw = raw.get("reminders", [])
    if not isinstance(raw, list):
        return []
    reminders = [dict(item) for item in raw if isinstance(item, dict)]
    return [item for item in reminders if str(item.get("id") or "").startswith("#")]


def _save(path: Path, reminders: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": 1,
        "updated_at": _timestamp(),
        "reminders": list(reminders),
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def list_replacement_reminders(path: str | Path | None = None) -> list[dict[str, Any]]:
    target = Path(path) if path is not None else default_replacement_reminder_path()
    reminders = _load(target)
    reminders.sort(key=lambda item: str(item.get("created_at") or ""))
    return reminders


def _next_id(reminders: list[dict[str, Any]], dt: datetime | None = None) -> str:
    prefix = _id_prefix(dt)
    used = {
        str(item.get("id") or "")
        for item in reminders
        if str(item.get("id") or "").startswith(prefix)
    }
    for idx in range(1, 1000):
        candidate = f"{prefix}-{idx:03d}"
        if candidate not in used:
            return candidate
    raise RuntimeError("Keine freie Erinnerungs-ID gefunden.")


def add_replacement_reminder(
    *,
    series_name: str,
    season: int | None,
    episode: int | None,
    episode_label: str,
    old_paths: Iterable[str | Path],
    new_path: str | Path,
    reason: str,
    path: str | Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    target = Path(path) if path is not None else default_replacement_reminder_path()
    reminders = _load(target)
    old_path_list = [str(p) for p in old_paths if str(p or "")]
    new_path_text = str(new_path or "")
    reason_text = str(reason or "").strip() or "Automatische SxxExx-Ersetzung"

    for item in reminders:
        if (
            [str(p) for p in item.get("old_paths", [])] == old_path_list
            and str(item.get("new_path") or "") == new_path_text
            and str(item.get("reason") or "") == reason_text
        ):
            return item

    created_at = _timestamp(now)
    reminder = {
        "id": _next_id(reminders, now),
        "created_at": created_at,
        "series_name": str(series_name or "").strip() or "unbekannt",
        "season": season,
        "episode": episode,
        "episode_label": str(episode_label or "").strip(),
        "old_paths": old_path_list,
        "old_filenames": [Path(p).name for p in old_path_list],
        "new_path": new_path_text,
        "new_filename": Path(new_path_text).name,
        "reason": reason_text,
    }
    reminders.append(reminder)
    _save(target, reminders)
    return reminder


def dismiss_replacement_reminders(ids: Iterable[str], path: str | Path | None = None) -> int:
    target = Path(path) if path is not None else default_replacement_reminder_path()
    remove = {str(value) for value in ids if str(value or "")}
    if not remove:
        return 0
    reminders = _load(target)
    kept = [item for item in reminders if str(item.get("id") or "") not in remove]
    removed = len(reminders) - len(kept)
    if removed:
        _save(target, kept)
    return removed


def has_replacement_reminders(path: str | Path | None = None) -> bool:
    return bool(list_replacement_reminders(path))
