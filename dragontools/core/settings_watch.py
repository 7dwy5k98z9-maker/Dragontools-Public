# -*- coding: utf-8 -*-
"""Persisted settings contract for Watch-Folder automation."""
from __future__ import annotations

import json
from dataclasses import asdict

from .settings_access import settings_bool, settings_int, settings_text, settings_value
from .watch_folder import WatchFolderRule

SET_KEY_WATCH_ENABLED = "automation/watch/enabled"
SET_KEY_WATCH_SCAN_INTERVAL = "automation/watch/scan_interval_seconds"
SET_KEY_WATCH_STABLE_SECONDS = "automation/watch/stable_seconds"
SET_KEY_WATCH_RULES = "automation/watch/rules_json"
SET_KEY_WATCH_PROCESSED_STATE = "automation/watch/processed_state_json"

DEFAULT_WATCH_ENABLED = False
DEFAULT_WATCH_SCAN_INTERVAL = 5
DEFAULT_WATCH_STABLE_SECONDS = 60


def load_watch_rules(settings) -> list[WatchFolderRule]:
    raw = settings_text(settings, SET_KEY_WATCH_RULES, "[]")
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    rules: list[WatchFolderRule] = []
    for entry in payload:
        rule = WatchFolderRule.from_mapping(entry)
        if rule is not None:
            rules.append(rule)
    return rules


def save_watch_rules(settings, rules: list[WatchFolderRule]) -> None:
    payload = [asdict(rule) for rule in rules]
    settings.setValue(SET_KEY_WATCH_RULES, json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def load_processed_state(settings) -> dict[str, str]:
    raw = settings_value(settings, SET_KEY_WATCH_PROCESSED_STATE, "{}")
    try:
        payload = json.loads(str(raw or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in payload.items()
        if str(key).strip() and str(value).strip()
    }


def save_processed_state(settings, state: dict[str, str], *, limit: int = 10000) -> None:
    items = list(state.items())[-max(1, int(limit)):]
    settings.setValue(
        SET_KEY_WATCH_PROCESSED_STATE,
        json.dumps(dict(items), ensure_ascii=False, separators=(",", ":")),
    )


def watch_enabled(settings) -> bool:
    return settings_bool(settings, SET_KEY_WATCH_ENABLED, DEFAULT_WATCH_ENABLED)


def watch_scan_interval(settings) -> int:
    return settings_int(
        settings, SET_KEY_WATCH_SCAN_INTERVAL, DEFAULT_WATCH_SCAN_INTERVAL,
        minimum=2, maximum=300,
    )


def watch_stable_seconds(settings) -> int:
    return settings_int(
        settings, SET_KEY_WATCH_STABLE_SECONDS, DEFAULT_WATCH_STABLE_SECONDS,
        minimum=5, maximum=3600,
    )


__all__ = [
    "SET_KEY_WATCH_ENABLED", "SET_KEY_WATCH_SCAN_INTERVAL", "SET_KEY_WATCH_STABLE_SECONDS",
    "SET_KEY_WATCH_RULES", "SET_KEY_WATCH_PROCESSED_STATE",
    "DEFAULT_WATCH_ENABLED", "DEFAULT_WATCH_SCAN_INTERVAL", "DEFAULT_WATCH_STABLE_SECONDS",
    "load_watch_rules", "save_watch_rules", "load_processed_state", "save_processed_state",
    "watch_enabled", "watch_scan_interval", "watch_stable_seconds",
]
