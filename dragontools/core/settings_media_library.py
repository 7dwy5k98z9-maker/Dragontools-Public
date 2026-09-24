# -*- coding: utf-8 -*-
"""Media-library database setting keys."""
from __future__ import annotations

SET_KEY_MEDIA_LIBRARY_ENABLED = "media_library/enabled"
SET_KEY_MEDIA_LIBRARY_PREFLIGHT_ENABLED = "media_library/preflight_enabled"
SET_KEY_MEDIA_LIBRARY_DB_PATH = "media_library/db_path"
SET_KEY_MEDIA_LIBRARY_PATH_MAPPINGS = "media_library/path_mappings_json"
SET_KEY_MEDIA_LIBRARY_LAST_JELLYFIN_DB = "media_library/last_jellyfin_db"
SET_KEY_MEDIA_LIBRARY_ANALYZE_ON_IMPORT = "media_library/analyze_on_import"
SET_KEY_MEDIA_LIBRARY_LANGUAGE_MODEL = "media_library/language_model"
SET_KEY_MEDIA_LIBRARY_LANGUAGE_MIN_CONFIDENCE = "media_library/language_min_confidence"
SET_KEY_MEDIA_LIBRARY_LANGUAGE_AUDIO_SAMPLES = "media_library/language_audio_samples"
SET_KEY_MEDIA_LIBRARY_LANGUAGE_SAMPLE_SECONDS = "media_library/language_sample_seconds"
SET_KEY_MEDIA_LIBRARY_OCR_LANGUAGES = "media_library/ocr_languages"
SET_KEY_MEDIA_LIBRARY_OCR_MIN_CONFIDENCE = "media_library/ocr_min_confidence"

DEFAULT_MEDIA_LIBRARY_ENABLED = False
DEFAULT_MEDIA_LIBRARY_PREFLIGHT_ENABLED = True
DEFAULT_MEDIA_LIBRARY_ANALYZE_ON_IMPORT = False
DEFAULT_MEDIA_LIBRARY_LANGUAGE_MODEL = "small"
DEFAULT_MEDIA_LIBRARY_LANGUAGE_MIN_CONFIDENCE = 85
DEFAULT_MEDIA_LIBRARY_LANGUAGE_AUDIO_SAMPLES = 3
DEFAULT_MEDIA_LIBRARY_LANGUAGE_SAMPLE_SECONDS = 15
DEFAULT_MEDIA_LIBRARY_OCR_LANGUAGES = "deu+eng"
DEFAULT_MEDIA_LIBRARY_OCR_MIN_CONFIDENCE = 75

__all__ = [name for name in globals() if name.startswith(("SET_KEY_", "DEFAULT_"))]
