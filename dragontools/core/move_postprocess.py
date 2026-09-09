# -*- coding: utf-8 -*-
"""Postprocessing nach erfolgreichem Media-Move."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Callable


def record_replacement_reminder(
    move_result: dict,
    dest_path: str,
    replaced_paths: list[str],
    *,
    log: Callable[[str, str], None],
) -> None:
    if not move_result.get("replacement_reminder_required"):
        return
    try:
        from .replacement_reminders import add_replacement_reminder

        reminder = add_replacement_reminder(
            series_name=str(move_result.get("episode_identity_series") or ""),
            season=move_result.get("episode_identity_season"),
            episode=move_result.get("episode_identity_episode"),
            episode_label=str(move_result.get("episode_identity_label") or ""),
            old_paths=replaced_paths,
            new_path=dest_path,
            reason=str(move_result.get("replacement_reason") or "Automatische SxxExx-Ersetzung"),
        )
        move_result["replacement_reminder_id"] = str(reminder.get("id") or "")
        log(f"🔴 Ersetzungs-Erinnerung gespeichert: {move_result['replacement_reminder_id']}", "warn")
    except (OSError, ValueError, TypeError) as exc:
        log(f"⚠️ Ersetzungs-Erinnerung konnte nicht gespeichert werden: {exc}", "warn")


def record_media_library_move(
    settings,
    *,
    source_path: str,
    move_result: dict | None,
    log: Callable[[str, str], None],
) -> None:
    if not move_result or not move_result.get("ok"):
        return
    dest_path = str(move_result.get("dest_path") or "")
    if not dest_path:
        return
    replaced_paths: list[str] = []
    if (
        move_result.get("deleted_existing")
        or move_result.get("replaced_existing")
        or move_result.get("episode_identity_replacement")
    ):
        replaced_paths = list(move_result.get("conflict_paths") or [])

    record_replacement_reminder(move_result, dest_path, replaced_paths, log=log)
    try:
        from .media_library_repository import record_moved_file_from_settings
        from .paths import get_tool_paths

        changed = record_moved_file_from_settings(
            settings,
            source_path=source_path,
            dest_path=dest_path,
            tools=get_tool_paths(),
            replaced_paths=replaced_paths,
        )
        if changed:
            log(f"🗄️ Mediathek-DB aktualisiert: {Path(dest_path).name}", "info")
    except (OSError, sqlite3.Error, ValueError, TypeError, RuntimeError) as exc:
        log(f"⚠️ Mediathek-DB konnte nicht aktualisiert werden: {exc}", "warn")
