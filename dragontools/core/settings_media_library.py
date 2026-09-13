# -*- coding: utf-8 -*-
"""Media-library database setting keys."""
from __future__ import annotations

SET_KEY_MEDIA_LIBRARY_ENABLED = "media_library/enabled"
SET_KEY_MEDIA_LIBRARY_PREFLIGHT_ENABLED = "media_library/preflight_enabled"
SET_KEY_MEDIA_LIBRARY_DB_PATH = "media_library/db_path"
SET_KEY_MEDIA_LIBRARY_PATH_MAPPINGS = "media_library/path_mappings_json"
SET_KEY_MEDIA_LIBRARY_LAST_JELLYFIN_DB = "media_library/last_jellyfin_db"
SET_KEY_MEDIA_LIBRARY_ANALYZE_ON_IMPORT = "media_library/analyze_on_import"

DEFAULT_MEDIA_LIBRARY_ENABLED = False
DEFAULT_MEDIA_LIBRARY_PREFLIGHT_ENABLED = True
DEFAULT_MEDIA_LIBRARY_ANALYZE_ON_IMPORT = False

__all__ = [name for name in globals() if name.startswith(("SET_KEY_", "DEFAULT_"))]
