# -*- coding: utf-8 -*-
"""Asynchronous best-effort Jellyfin refresh dispatch from GUI workflows."""
from __future__ import annotations

from PyQt6.QtCore import QSettings, QThread, pyqtSignal

from ..core.jellyfin_api import JellyfinApiError
from ..core.jellyfin_refresh_service import (
    JellyfinRefreshConfig,
    build_move_updates,
    build_rename_updates,
    execute_refresh,
    merge_refresh_mappings,
)
from ..core.media_library_path_mappings import get_path_mappings, load_path_mappings
from ..core.media_library_types import default_media_library_db_path
from ..core.settings_app import APP_NAME, APP_ORG
from ..core.secret_settings import read_secret
from ..core.settings_jellyfin import (
    DEFAULT_JELLYFIN_API_ENABLED,
    DEFAULT_JELLYFIN_FALLBACK_FULL_SCAN,
    DEFAULT_JELLYFIN_NOTIFY_AFTER_MOVE,
    DEFAULT_JELLYFIN_NOTIFY_AFTER_RENAME,
    DEFAULT_JELLYFIN_REFRESH_MODE,
    SET_KEY_JELLYFIN_API_ENABLED,
    SET_KEY_JELLYFIN_API_KEY,
    SET_KEY_JELLYFIN_FALLBACK_FULL_SCAN,
    SET_KEY_JELLYFIN_NOTIFY_AFTER_MOVE,
    SET_KEY_JELLYFIN_NOTIFY_AFTER_RENAME,
    SET_KEY_JELLYFIN_REFRESH_MODE,
    SET_KEY_JELLYFIN_SERVER_URL,
)
from ..core.settings_media_library import (
    SET_KEY_MEDIA_LIBRARY_DB_PATH,
    SET_KEY_MEDIA_LIBRARY_PATH_MAPPINGS,
)

_ACTIVE_WORKERS: set[QThread] = set()
_SHUTTING_DOWN = False


def stop_jellyfin_workers(*, timeout_ms=8000) -> bool:
    from .application_shutdown import shutdown_workers
    global _SHUTTING_DOWN
    _SHUTTING_DOWN = True
    result = shutdown_workers(tuple(_ACTIVE_WORKERS), timeout_ms=timeout_ms)
    if not result.ok:
        _SHUTTING_DOWN = False
    return result.ok


class _JellyfinRefreshWorker(QThread):
    completed = pyqtSignal(bool, str, bool)

    def __init__(self, config: JellyfinRefreshConfig, updates: list[dict[str, str]]) -> None:
        super().__init__()
        self._config = config
        self._updates = list(updates)

    def run(self) -> None:
        try:
            result = execute_refresh(self._config, self._updates)
        except Exception as exc:
            self.completed.emit(False, str(exc), False)
            return
        self.completed.emit(result.ok, result.message, result.fallback_used)


def _settings_snapshot(settings: QSettings, *, trigger: str):
    if not settings.value(SET_KEY_JELLYFIN_API_ENABLED, DEFAULT_JELLYFIN_API_ENABLED, type=bool):
        return None
    trigger_key = (
        SET_KEY_JELLYFIN_NOTIFY_AFTER_RENAME
        if trigger == "rename"
        else SET_KEY_JELLYFIN_NOTIFY_AFTER_MOVE
    )
    trigger_default = (
        DEFAULT_JELLYFIN_NOTIFY_AFTER_RENAME
        if trigger == "rename"
        else DEFAULT_JELLYFIN_NOTIFY_AFTER_MOVE
    )
    if not settings.value(trigger_key, trigger_default, type=bool):
        return None

    server_url = settings.value(SET_KEY_JELLYFIN_SERVER_URL, "", type=str).strip()
    api_key = read_secret(settings, SET_KEY_JELLYFIN_API_KEY).strip()
    if not server_url or not api_key:
        raise JellyfinApiError("Jellyfin-Integration ist aktiviert, aber Serveradresse oder API-Key fehlt.")

    refresh_mode = settings.value(
        SET_KEY_JELLYFIN_REFRESH_MODE,
        DEFAULT_JELLYFIN_REFRESH_MODE,
        type=str,
    )
    if refresh_mode not in {"targeted", "full"}:
        refresh_mode = DEFAULT_JELLYFIN_REFRESH_MODE

    # Renamer updates are advisory only.  A rename can happen outside the
    # Jellyfin library roots, so it must never escalate into /Library/Refresh.
    # Full scans are reserved for the move workflow after the file reached its
    # final media-library destination.
    if trigger == "rename":
        refresh_mode = "targeted"
        fallback_full_scan = False
    else:
        fallback_full_scan = settings.value(
            SET_KEY_JELLYFIN_FALLBACK_FULL_SCAN,
            DEFAULT_JELLYFIN_FALLBACK_FULL_SCAN,
            type=bool,
        )

    config = JellyfinRefreshConfig(
        server_url=server_url,
        api_key=api_key,
        refresh_mode=refresh_mode,
        fallback_full_scan=fallback_full_scan,
    )
    configured_mappings = load_path_mappings(
        settings.value(SET_KEY_MEDIA_LIBRARY_PATH_MAPPINGS, "", type=str)
    )
    db_path = settings.value(
        SET_KEY_MEDIA_LIBRARY_DB_PATH,
        str(default_media_library_db_path()),
        type=str,
    ).strip()
    try:
        stored_mappings = get_path_mappings(db_path) if db_path else []
    except Exception:
        # Jellyfin refresh is best-effort. A temporarily unavailable/corrupt
        # media-library DB must not disable the already persisted QSettings
        # mapping. Server-side path validation still protects the API call.
        stored_mappings = []
    mappings = merge_refresh_mappings(configured_mappings, stored_mappings)
    return config, mappings


def _start_worker(config: JellyfinRefreshConfig, updates: list[dict[str, str]], log) -> bool:
    if not updates or _SHUTTING_DOWN:
        return False
    worker = _JellyfinRefreshWorker(config, updates)
    _ACTIVE_WORKERS.add(worker)

    def _completed(ok: bool, message: str, fallback_used: bool) -> None:
        if log is None or _SHUTTING_DOWN:
            return
        if fallback_used:
            log(f"⚠️ {message}", "warn")
        elif ok:
            log(f"✅ {message}", "info")
        else:
            log(f"⚠️ Jellyfin-Aktualisierung fehlgeschlagen: {message}", "warn")

    def _retire() -> None:
        _ACTIVE_WORKERS.discard(worker)
        worker.deleteLater()

    worker.completed.connect(_completed)
    worker.finished.connect(_retire)
    if log is not None:
        log("🔄 Jellyfin wird im Hintergrund aktualisiert …", "info")
    worker.start()
    return True


def dispatch_after_move(move_log: list, log=None, *, settings: QSettings | None = None) -> bool:
    settings = settings or QSettings(APP_ORG, APP_NAME)
    try:
        snapshot = _settings_snapshot(settings, trigger="move")
        if snapshot is None:
            return False
        config, mappings = snapshot
        updates = build_move_updates(move_log, mappings)
        return _start_worker(config, updates, log)
    except Exception as exc:
        if log is not None:
            log(f"⚠️ Jellyfin-Aktualisierung übersprungen: {exc}", "warn")
        return False


def dispatch_after_rename(
    renamed_paths: list[tuple[str, str]],
    log=None,
    *,
    settings: QSettings | None = None,
) -> bool:
    settings = settings or QSettings(APP_ORG, APP_NAME)
    try:
        snapshot = _settings_snapshot(settings, trigger="rename")
        if snapshot is None:
            return False
        config, mappings = snapshot
        updates = build_rename_updates(renamed_paths, mappings)
        return _start_worker(config, updates, log)
    except Exception as exc:
        if log is not None:
            log(f"⚠️ Jellyfin-Aktualisierung übersprungen: {exc}", "warn")
        return False
