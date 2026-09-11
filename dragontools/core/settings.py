# -*- coding: utf-8 -*-
"""
Zentrale Settings-Konstanten für DragonTools V9.
Alle QSettings-Keys an einem einzigen Ort – nie mehr in mehreren Dateien.
"""
from __future__ import annotations

from typing import Any, Iterable

from .type_utils import _safe_bool, _safe_float, _safe_int
from .version import APP_VERSION
 
APP_ORG  = "DragonDeveloper"
APP_NAME = "Dragon Tools"

SET_KEY_UI_SECTION_PREFIX = "ui/sections"


def ui_section_expanded_key(section_id: str) -> str:
    """QSettings-Key fuer den offenen/geschlossenen Zustand eines UI-Bereichs."""
    safe = str(section_id or "").strip().replace("\\", "/").strip("/")
    parts = [part.strip().replace(" ", "_") for part in safe.split("/") if part.strip()]
    name = "/".join(parts) or "default"
    return f"{SET_KEY_UI_SECTION_PREFIX}/{name}/expanded"


def app_qsettings():
    """Erzeugt die zentrale QSettings-Instanz lazy und ohne harte Core-Abhängigkeit."""
    try:
        from PyQt6.QtCore import QSettings

        return QSettings(APP_ORG, APP_NAME)
    except Exception:
        return None


def settings_value(settings, key: str, default: Any = None, *, value_type=None) -> Any:
    """Liest einen QSettings-Wert robust mit Fallback.

    Viele Tests und Worker übergeben bewusst Fake-Settings oder None. Dieser
    Helfer vereinheitlicht die Fehlerbehandlung, ohne solche Aufrufer an echte
    Windows-QSettings zu koppeln.
    """
    if settings is None:
        return default
    try:
        if value_type is not None:
            return settings.value(key, default, type=value_type)
        return settings.value(key, default)
    except TypeError:
        try:
            return settings.value(key, default)
        except Exception:
            return default
    except Exception:
        return default


def settings_bool(settings, key: str, default: bool) -> bool:
    return _safe_bool(settings_value(settings, key, default), default)


def settings_int(
    settings,
    key: str,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    value = settings_value(settings, key, default)
    number = _safe_int(value, int(default))
    if number is None:
        number = int(default)
    if minimum is not None:
        number = max(int(minimum), number)
    if maximum is not None:
        number = min(int(maximum), number)
    return number


def settings_float(
    settings,
    key: str,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    value = settings_value(settings, key, default)
    number = _safe_float(value, float(default))
    if minimum is not None:
        number = max(float(minimum), number)
    if maximum is not None:
        number = min(float(maximum), number)
    return number


def settings_text(
    settings,
    key: str,
    default: str = "",
    *,
    allowed: Iterable[str] | None = None,
) -> str:
    value = settings_value(settings, key, default, value_type=str)
    text = str(value or "").strip()
    if not text:
        text = str(default or "")
    if allowed is not None and text not in set(allowed):
        return str(default or "")
    return text
 
# ---------------------------------------------------------------------------
# Globale Fallback-Pfade (Legacy-Kompatibilität)
# ---------------------------------------------------------------------------
SET_KEY_PATH_TV    = "paths/tv"
SET_KEY_PATH_ANIME = "paths/anime"
SET_KEY_PATH_FILME = "paths/filme"
 
# ---------------------------------------------------------------------------
# Zielcontainer
# ---------------------------------------------------------------------------
SET_KEY_OUTPUT_CONTAINER_STANDARD = "convert/output_container_standard"
SET_KEY_OUTPUT_CONTAINER_DV = "convert/output_container_dv"
DEFAULT_OUTPUT_CONTAINER_STANDARD = "mkv"
DEFAULT_OUTPUT_CONTAINER_DV = "mp4"

# ---------------------------------------------------------------------------
# Codec-spezifische Zielpfade
# ---------------------------------------------------------------------------
SET_KEY_PATH_H264_TV    = "paths/h264/tv"
SET_KEY_PATH_H264_ANIME = "paths/h264/anime"
SET_KEY_PATH_H264_FILME = "paths/h264/filme"
 
SET_KEY_PATH_H265_TV    = "paths/h265/tv"
SET_KEY_PATH_H265_ANIME = "paths/h265/anime"
SET_KEY_PATH_H265_FILME = "paths/h265/filme"
 
SET_KEY_PATH_AV1_TV     = "paths/av1/tv"
SET_KEY_PATH_AV1_ANIME  = "paths/av1/anime"
SET_KEY_PATH_AV1_FILME  = "paths/av1/filme"
 
# ---------------------------------------------------------------------------
# Aktiv-Flags (global je Medientyp)
# ---------------------------------------------------------------------------
 
# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
SET_KEY_H264_LOG_ROOT    = "paths/h264_log_root"
SET_KEY_H264_LOG_ENABLED = "logging/h264_enabled"
SET_KEY_H265_LOG_ROOT    = "paths/h265_log_root"
SET_KEY_H265_LOG_ENABLED = "logging/h265_enabled"
SET_KEY_AV1_LOG_ROOT     = "paths/av1_log_root"
SET_KEY_AV1_LOG_ENABLED  = "logging/av1_enabled"

# Dragon Tools behandelt Logging global. Der sichtbare Settings-Eintrag ist
# historisch unter den H.265-Keys gespeichert; die weiteren Keys bleiben nur
# als Legacy-Speicherorte erhalten und werden beim Laden/Speichern gespiegelt.
SET_KEY_LOG_ROOT         = SET_KEY_H265_LOG_ROOT
SET_KEY_LOG_ENABLED      = SET_KEY_H265_LOG_ENABLED
LOG_ROOT_KEYS = (
    SET_KEY_LOG_ROOT,
    SET_KEY_H264_LOG_ROOT,
    SET_KEY_AV1_LOG_ROOT,
)
LOG_ENABLED_KEYS = (
    SET_KEY_LOG_ENABLED,
    SET_KEY_H264_LOG_ENABLED,
    SET_KEY_AV1_LOG_ENABLED,
)
 
# ---------------------------------------------------------------------------
# Größenprüfung
# ---------------------------------------------------------------------------
SET_KEY_ALLOW_GROWTH        = "storage/allow_bigger_than_source"
SET_KEY_SAVE_ALLOW_LARGER_OUTPUT = "save/allow_larger_output"
SET_KEY_SAVE_ALLOW_LARGER_OUTPUT_PERCENT = "save/allow_larger_output_percent"
SET_KEY_SAVE_MIN_OUTPUT_SIZE_ENABLED = "save/min_output_size_enabled"
SET_KEY_SAVE_MIN_OUTPUT_SIZE_PERCENT = "save/min_output_size_percent"
 
# ---------------------------------------------------------------------------
# Tool-Pfade (Custom-Override)
# ---------------------------------------------------------------------------
TOOL_KEYS: dict[str, tuple[str, str]] = {
    "ffmpeg":         ("tools/ffmpeg/use_custom",        "tools/ffmpeg/dir"),
    # ffprobe hat keinen eigenen Key – liegt immer im gleichen Ordner wie ffmpeg
    "mkv":            ("tools/mkv/use_custom",           "tools/mkv/dir"),
    "makemkvcon":     ("tools/makemkvcon/use_custom",    "tools/makemkvcon/dir"),
    "rmts":           ("tools/rmts/use_custom",          "tools/rmts/dir"),
    "handbrake":      ("tools/handbrake/use_custom",     "tools/handbrake/dir"),
    "mediainfo":      ("tools/mediainfo/use_custom",     "tools/mediainfo/dir"),
    "dovi_tool":      ("tools/dovi_tool/use_custom",     "tools/dovi_tool/dir"),
    "hdr10plus_tool": ("tools/hdr10plus_tool/use_custom","tools/hdr10plus_tool/dir"),
    "mp4box":         ("tools/mp4box/use_custom",        "tools/mp4box/dir"),
}
 
# ---------------------------------------------------------------------------
# Profil-Labels (Anzeigename ↔ interner Key)
# ---------------------------------------------------------------------------
PROFILE_LABELS = {
    "film":  "Filme",
    "anime": "Anime",
    "tv":    "TV",
}
PROFILE_LABELS_REVERSE = {v: k for k, v in PROFILE_LABELS.items()}
 
# ---------------------------------------------------------------------------
# Standard-Profile (Fallback wenn keine gespeicherten vorhanden)
# ---------------------------------------------------------------------------
DEFAULT_PROFILES: dict[str, dict] = {
    "film_h265":  {"label": "Film H.265",  "codec": "h265", "crf": 22, "preset": "medium",   "scale": None},
    "tv_h265":    {"label": "TV H.265",    "codec": "h265", "crf": 22, "preset": "medium",   "scale": None},
    "anime_h265": {"label": "Anime H.265", "codec": "h265", "crf": 20, "preset": "slow",     "scale": None},
    "film_h264":  {"label": "Film H.264",  "codec": "h264", "crf": 22, "preset": "medium",   "scale": None},
    "tv_h264":    {"label": "TV H.264",    "codec": "h264", "crf": 21, "preset": "medium",   "scale": None},
    "anime_h264": {"label": "Anime H.264", "codec": "h264", "crf": 19, "preset": "slow",     "scale": None},
    "film_av1":   {"label": "Film AV1",    "codec": "av1",  "crf": 28, "preset": "6",        "scale": None},
    "tv_av1":     {"label": "TV AV1",      "codec": "av1",  "crf": 27, "preset": "6",        "scale": None},
    "anime_av1":  {"label": "Anime AV1",   "codec": "av1",  "crf": 25, "preset": "5",        "scale": None},
}
 
# Auto-Crop global
SET_KEY_AUTOCROP_ENABLED = "convert/autocrop_enabled"
SET_KEY_AUTOCROP_MODE = "convert/autocrop_mode"
SET_KEY_AUTOCROP_PROBE_START = "convert/autocrop_probe_start_s"
SET_KEY_AUTOCROP_PROBE_DURATION = "convert/autocrop_probe_duration_s"
SET_KEY_AUTOCROP_PROBE_INTERVAL = "convert/autocrop_probe_interval_s"
DEFAULT_AUTOCROP_MODE = "single"
DEFAULT_AUTOCROP_PROBE_START_S = 30
DEFAULT_AUTOCROP_PROBE_DURATION_S = 45
DEFAULT_AUTOCROP_PROBE_INTERVAL_S = 600
# IMAX Auto-Erkennung
SET_KEY_IMAX_DETECT      = "convert/imax_auto_detect"
SET_KEY_IMAX_PROBE_INTERVAL = "convert/imax_probe_interval_s"
SET_KEY_IMAX_PROBE_DURATION = "convert/imax_probe_duration_s"
SET_KEY_IMAX_MIN_VARIANCE_PERCENT = "convert/imax_min_variance_percent"
SET_KEY_IMAX_MIN_HITS = "convert/imax_min_hits"
DEFAULT_IMAX_PROBE_INTERVAL_S = 90
DEFAULT_IMAX_PROBE_DURATION_S = 3
DEFAULT_IMAX_MIN_VARIANCE_PERCENT = 15
DEFAULT_IMAX_MIN_HITS = 2
# DV / HDR10+ Pipeline-Policy (codecbezogen)
# True  = dynamische HDR-Metadaten erhalten, wenn die Quelle sie besitzt.
# False = Metadaten bewusst ignorieren und Standard-Pipeline verwenden.
SET_KEY_PRESERVE_DV      = "encoder/h265/preserve_dv"
SET_KEY_PRESERVE_HDRPLUS = "encoder/h265/preserve_hdrplus"
SET_KEY_AV1_PRESERVE_DV      = "encoder/av1/preserve_dv"
SET_KEY_AV1_PRESERVE_HDRPLUS = "encoder/av1/preserve_hdrplus"

# ---------------------------------------------------------------------------
# Output-Validierung / Laufzeit-Reparatur
# ---------------------------------------------------------------------------
SET_KEY_OUTPUT_MIN_SIZE_KB = "validation/output_min_size_kb"
SET_KEY_OUTPUT_DURATION_MIN_PERCENT = "validation/duration_min_percent"
SET_KEY_OUTPUT_DURATION_MAX_PERCENT = "validation/duration_max_percent"
SET_KEY_OUTPUT_DURATION_MAX_EXTRA_S = "validation/duration_max_extra_s"
DEFAULT_OUTPUT_MIN_SIZE_KB = 1
DEFAULT_OUTPUT_DURATION_MIN_PERCENT = 90
DEFAULT_OUTPUT_DURATION_MAX_PERCENT = 125
DEFAULT_OUTPUT_DURATION_MAX_EXTRA_S = 60

SET_KEY_REPAIR_DURATION_REMUX_ENABLED = "repair/duration/remux_enabled"
SET_KEY_REPAIR_DURATION_TIMESTAMP_ENABLED = "repair/duration/timestamp_enabled"
DEFAULT_REPAIR_DURATION_REMUX_ENABLED = True
DEFAULT_REPAIR_DURATION_TIMESTAMP_ENABLED = True

# ---------------------------------------------------------------------------
# Verbose / Debug Logging (separates ausführliches Log)
# ---------------------------------------------------------------------------
SET_KEY_VERBOSE_LOG_ROOT    = "logging/verbose_log_root"
SET_KEY_VERBOSE_LOG_ENABLED = "logging/verbose_log_enabled"

# ---------------------------------------------------------------------------
# Move-Aktivierung pro Kategorie
# ---------------------------------------------------------------------------
SET_KEY_ACTIVE_ALL_TV    = "move/active_tv"
SET_KEY_ACTIVE_ALL_ANIME = "move/active_anime"
SET_KEY_ACTIVE_ALL_FILME = "move/active_filme"
# Standard-Zieltyp für Serien im Preflight-Dialog ("Anime" oder "TV")
SET_KEY_SERIES_DEFAULT_TYPE = "move/series_default_type"
# Countdown-Sekunden vor automatischem Herunterfahren
SET_KEY_SHUTDOWN_COUNTDOWN  = "move/shutdown_countdown_seconds"
# Verhalten wenn Zieldatei bzw. gleichnamige Videodatei beim Verschieben bereits existiert
# Mögliche Werte: "skip" | "delete_first" | "overwrite" | "rename"
SET_KEY_MOVE_CONFLICT       = "move/conflict_mode"
SET_KEY_PREFLIGHT_SAVE_REPORT = "preflight/save_report"

# ---------------------------------------------------------------------------
# Parallele Bearbeitung
# ---------------------------------------------------------------------------
SET_KEY_PARALLEL_CPU_JOBS = "parallel/cpu_jobs"
SET_KEY_PARALLEL_GPU_JOBS = "parallel/gpu_jobs"
SET_KEY_PARALLEL_DEFAULTS_MIGRATED = "parallel/defaults_cpu1_gpu2_migrated"
DEFAULT_PARALLEL_CPU_JOBS = 1
DEFAULT_PARALLEL_GPU_JOBS = 2
MAX_PARALLEL_JOBS = 8

# ---------------------------------------------------------------------------
# Online-Metadaten / Provider, TMDB, TheTVDB
# ---------------------------------------------------------------------------
SET_KEY_METADATA_MOVIE_PROVIDER = "metadata/provider/movie"
SET_KEY_METADATA_SERIES_PROVIDER = "metadata/provider/series"
SET_KEY_METADATA_MOVIE_PREFERRED_PROVIDER = "metadata/provider/movie_preferred"
SET_KEY_METADATA_SERIES_PREFERRED_PROVIDER = "metadata/provider/series_preferred"
SET_KEY_METADATA_TMDB_ENABLED = "metadata/tmdb/enabled"
SET_KEY_METADATA_TMDB_API_KEY = str("metadata/tmdb/api_key")
SET_KEY_METADATA_TMDB_READ_TOKEN = "metadata/tmdb/read_access_token"
SET_KEY_METADATA_TVDB_ENABLED = "metadata/thetvdb/enabled"
SET_KEY_METADATA_TVDB_API_KEY = str("metadata/thetvdb/api_key")
SET_KEY_METADATA_TVDB_PIN = "metadata/thetvdb/pin"
SET_KEY_METADATA_TVDB_BEARER_TOKEN = "metadata/thetvdb/bearer_token"
SET_KEY_METADATA_LANGUAGE = "metadata/language"
SET_KEY_METADATA_FALLBACK_LANGUAGE = "metadata/fallback_language"
SET_KEY_METADATA_CACHE_ENABLED = "metadata/cache_enabled"
SET_KEY_METADATA_CACHE_DAYS = "metadata/cache_days"

DEFAULT_METADATA_MOVIE_PROVIDER = "tmdb"
DEFAULT_METADATA_SERIES_PROVIDER = "tmdb"
DEFAULT_METADATA_MOVIE_PREFERRED_PROVIDER = "tmdb"
DEFAULT_METADATA_SERIES_PREFERRED_PROVIDER = "tmdb"
DEFAULT_METADATA_LANGUAGE = "de-DE"
DEFAULT_METADATA_FALLBACK_LANGUAGE = "en-US"
DEFAULT_METADATA_CACHE_ENABLED = True
DEFAULT_METADATA_CACHE_DAYS = 30

# ---------------------------------------------------------------------------
# Mediathek-Datenbank / SQLite-Bestand
# ---------------------------------------------------------------------------
SET_KEY_MEDIA_LIBRARY_ENABLED = "media_library/enabled"
SET_KEY_MEDIA_LIBRARY_PREFLIGHT_ENABLED = "media_library/preflight_enabled"
SET_KEY_MEDIA_LIBRARY_DB_PATH = "media_library/db_path"
SET_KEY_MEDIA_LIBRARY_PATH_MAPPINGS = "media_library/path_mappings_json"
SET_KEY_MEDIA_LIBRARY_LAST_JELLYFIN_DB = "media_library/last_jellyfin_db"
SET_KEY_MEDIA_LIBRARY_ANALYZE_ON_IMPORT = "media_library/analyze_on_import"

DEFAULT_MEDIA_LIBRARY_ENABLED = False
DEFAULT_MEDIA_LIBRARY_PREFLIGHT_ENABLED = True
DEFAULT_MEDIA_LIBRARY_ANALYZE_ON_IMPORT = False

# ---------------------------------------------------------------------------
# Jellyfin / Post-Processing
# ---------------------------------------------------------------------------
SET_KEY_NFO_ENABLED = "postprocess/nfo/enabled"
SET_KEY_NFO_ONLY_UNAMBIGUOUS = "postprocess/nfo/only_unambiguous"
SET_KEY_NFO_FILEINFO_ENABLED = "postprocess/nfo/fileinfo_enabled"
SET_KEY_NFO_MOVIE_TARGET_NAME = "postprocess/nfo/movie_target_name"
SET_KEY_NFO_CONFLICT_MODE = "postprocess/nfo/conflict_mode"

DEFAULT_NFO_ENABLED = False
DEFAULT_NFO_ONLY_UNAMBIGUOUS = True
DEFAULT_NFO_FILEINFO_ENABLED = True
DEFAULT_NFO_MOVIE_TARGET_NAME = "movie.nfo"
DEFAULT_NFO_CONFLICT_MODE = "skip"

SET_KEY_TRICKPLAY_ENABLED = "postprocess/trickplay/enabled"
SET_KEY_TRICKPLAY_ONLY_MISSING = "postprocess/trickplay/only_missing"
SET_KEY_TRICKPLAY_WIDTH = "postprocess/trickplay/width"
SET_KEY_TRICKPLAY_TILE_COLUMNS = "postprocess/trickplay/tile_columns"
SET_KEY_TRICKPLAY_TILE_ROWS = "postprocess/trickplay/tile_rows"
SET_KEY_TRICKPLAY_INTERVAL_S = "postprocess/trickplay/interval_s"
SET_KEY_TRICKPLAY_JPEG_QUALITY = "postprocess/trickplay/jpeg_quality"
SET_KEY_TRICKPLAY_QSCALE = "postprocess/trickplay/qscale"
SET_KEY_TRICKPLAY_HWACCEL = "postprocess/trickplay/hwaccel"
SET_KEY_TRICKPLAY_MAX_JOBS = "postprocess/trickplay/max_jobs"
SET_KEY_TRICKPLAY_SOURCE_MODE = "postprocess/trickplay/source_mode"
SET_KEY_TRICKPLAY_CONFLICT_MODE = "postprocess/trickplay/conflict_mode"

DEFAULT_TRICKPLAY_ENABLED = False
DEFAULT_TRICKPLAY_ONLY_MISSING = True
DEFAULT_TRICKPLAY_WIDTH = 320
DEFAULT_TRICKPLAY_TILE_COLUMNS = 10
DEFAULT_TRICKPLAY_TILE_ROWS = 10
DEFAULT_TRICKPLAY_INTERVAL_S = 10
DEFAULT_TRICKPLAY_JPEG_QUALITY = 90
DEFAULT_TRICKPLAY_QSCALE = 4
DEFAULT_TRICKPLAY_HWACCEL = "cuda"
DEFAULT_TRICKPLAY_MAX_JOBS = 1
DEFAULT_TRICKPLAY_SOURCE_MODE = "output"  # "output" | "source"
DEFAULT_TRICKPLAY_CONFLICT_MODE = "skip"

# ---------------------------------------------------------------------------
# Quellbildprüfung
# ---------------------------------------------------------------------------
SET_KEY_SOURCE_VISUAL_CHECK_ENABLED = "source_visual_check/enabled"
SET_KEY_SOURCE_VISUAL_CHECK_INTERVAL_PERCENT = "source_visual_check/interval_percent"
SET_KEY_SOURCE_VISUAL_CHECK_SAMPLE_DURATION_S = "source_visual_check/sample_duration_s"
SET_KEY_SOURCE_VISUAL_CHECK_FPS = "source_visual_check/fps"
SET_KEY_SOURCE_VISUAL_CHECK_BLOCK_PERCENT = "source_visual_check/block_percent"
SET_KEY_SOURCE_VISUAL_CHECK_MIN_HITS = "source_visual_check/min_hits"

DEFAULT_SOURCE_VISUAL_CHECK_ENABLED = True
DEFAULT_SOURCE_VISUAL_CHECK_INTERVAL_PERCENT = 10
DEFAULT_SOURCE_VISUAL_CHECK_SAMPLE_DURATION_S = 2
DEFAULT_SOURCE_VISUAL_CHECK_FPS = 2
DEFAULT_SOURCE_VISUAL_CHECK_BLOCK_PERCENT = 80
DEFAULT_SOURCE_VISUAL_CHECK_MIN_HITS = 4

SENSITIVE_SETTINGS_KEYS = {
    SET_KEY_METADATA_TMDB_API_KEY,
    SET_KEY_METADATA_TMDB_READ_TOKEN,
    SET_KEY_METADATA_TVDB_API_KEY,
    SET_KEY_METADATA_TVDB_PIN,
    SET_KEY_METADATA_TVDB_BEARER_TOKEN,
}
