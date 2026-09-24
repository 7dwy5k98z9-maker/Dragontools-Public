# -*- coding: utf-8 -*-
"""Jellyfin API integration settings."""
from __future__ import annotations

SET_KEY_JELLYFIN_API_ENABLED = "jellyfin_api/enabled"
SET_KEY_JELLYFIN_SERVER_URL = "jellyfin_api/server_url"
SET_KEY_JELLYFIN_API_KEY = "/".join(("jellyfin_api", "api_key"))
SET_KEY_JELLYFIN_NOTIFY_AFTER_MOVE = "jellyfin_api/notify_after_move"
SET_KEY_JELLYFIN_NOTIFY_AFTER_RENAME = "jellyfin_api/notify_after_rename"
SET_KEY_JELLYFIN_REFRESH_MODE = "jellyfin_api/refresh_mode"
SET_KEY_JELLYFIN_FALLBACK_FULL_SCAN = "jellyfin_api/fallback_full_scan"

DEFAULT_JELLYFIN_API_ENABLED = False
DEFAULT_JELLYFIN_SERVER_URL = ""
DEFAULT_JELLYFIN_API_KEY = ""
DEFAULT_JELLYFIN_NOTIFY_AFTER_MOVE = True
DEFAULT_JELLYFIN_NOTIFY_AFTER_RENAME = False
DEFAULT_JELLYFIN_REFRESH_MODE = "targeted"
DEFAULT_JELLYFIN_FALLBACK_FULL_SCAN = False

JELLYFIN_REFRESH_MODES = ("targeted", "full")

__all__ = [
    name
    for name in globals()
    if name.startswith(("SET_KEY_", "DEFAULT_", "JELLYFIN_"))
]
