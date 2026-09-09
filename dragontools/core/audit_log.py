# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .settings import (
    APP_NAME,
    APP_ORG,
    LOG_ROOT_KEYS,
    SENSITIVE_SETTINGS_KEYS,
)


def settings_change_log_dir(settings=None, *, log_root: str | Path | None = None) -> Path:
    base = Path(log_root) if log_root else _log_base_from_settings(settings)
    path = base / "Logging" / "SettingsChanges"
    path.mkdir(parents=True, exist_ok=True)
    return path


def append_audit_event(
    action: str,
    details: str | None = None,
    *,
    settings=None,
    log_root: str | Path | None = None,
) -> Path | None:
    """Schreibt einen kurzen nachvollziehbaren Eintrag ins Änderungsprotokoll."""
    action = str(action or "").strip()
    if not action:
        return None
    try:
        log_dir = settings_change_log_dir(settings, log_root=log_root)
        target = log_dir / f"settings_changes_{datetime.now().strftime('%Y-%m')}.txt"
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        suffix = f" | {details.strip()}" if details and str(details).strip() else ""
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(f"[{ts}] {action}{suffix}\n")
        return target
    except Exception:
        return None


def snapshot_qsettings(settings, keys: list[str] | tuple[str, ...] | None = None) -> dict[str, Any]:
    try:
        selected = list(keys) if keys is not None else list(settings.allKeys())
    except Exception:
        selected = list(keys or [])
    result: dict[str, Any] = {}
    for key in selected:
        try:
            result[str(key)] = settings.value(str(key), None)
        except Exception:
            result[str(key)] = None
    return result


def summarize_changes(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    max_items: int = 14,
) -> tuple[int, str]:
    changed: list[str] = []
    for key in sorted(set(before) | set(after)):
        old = before.get(key)
        new = after.get(key)
        if str(old) == str(new):
            continue
        changed.append(f"{key}: {_display_value(key, old)} -> {_display_value(key, new)}")
    if not changed:
        return 0, "keine Wertänderung"
    shown = changed[: max(1, int(max_items or 1))]
    rest = len(changed) - len(shown)
    if rest > 0:
        shown.append(f"... +{rest} weitere Änderung(en)")
    return len(changed), "; ".join(shown)


def log_qsettings_changes(
    section: str,
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    settings=None,
) -> Path | None:
    count, summary = summarize_changes(before, after)
    action = f"{section}: {count} Änderung(en)" if count else f"{section}: gespeichert"
    return append_audit_event(action, summary, settings=settings)


def _display_value(key: str, value: Any) -> str:
    if key in SENSITIVE_SETTINGS_KEYS:
        return "***" if value not in (None, "") else ""
    text = str(value)
    if len(text) > 90:
        text = text[:87] + "..."
    return text


def _log_base_from_settings(settings=None) -> Path:
    try:
        from PyQt6.QtCore import QSettings

        s = settings or QSettings(APP_ORG, APP_NAME)
        for key in LOG_ROOT_KEYS:
            root = s.value(key, "", type=str)
            if root and root.strip():
                return Path(root.strip())
    except Exception:
        pass
    return Path.home() / "Documents" / "DragonTools"
