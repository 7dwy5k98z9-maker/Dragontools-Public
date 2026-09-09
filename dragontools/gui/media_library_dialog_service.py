# -*- coding: utf-8 -*-
"""Qt-unabhängige Anwendungsservices für den Mediathek-Dialog.

Der Service kapselt die fachlichen Core-Aufrufe und das Mapping zwischen
QSettings-artigen Speichern und einfachen Datenobjekten. Er zeigt bewusst
keine Dialoge und kennt keine Widgets.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.media_library_db import (
    cleanup_inactive_media_items,
    execute_sql,
    get_stats,
    initialize_database,
    normalize_database_stream_types,
)
from ..core.media_library_export import (
    export_database,
    export_database_to_csv,
    export_search_results_to_csv,
)
from ..core.media_library_jellyfin import import_jellyfin_database
from ..core.media_library_paths import dump_path_mappings, load_path_mappings, save_path_mappings
from ..core.media_library_search import search_library
from ..core.media_library_types import PathMapping, default_media_library_db_path
from ..core.paths import default_target_path_for_settings_key, get_tool_paths, normalize_user_path, path_compare_key
from ..core.settings import (
    DEFAULT_MEDIA_LIBRARY_ANALYZE_ON_IMPORT,
    DEFAULT_MEDIA_LIBRARY_ENABLED,
    DEFAULT_MEDIA_LIBRARY_PREFLIGHT_ENABLED,
    SET_KEY_MEDIA_LIBRARY_ANALYZE_ON_IMPORT,
    SET_KEY_MEDIA_LIBRARY_DB_PATH,
    SET_KEY_MEDIA_LIBRARY_ENABLED,
    SET_KEY_MEDIA_LIBRARY_LAST_JELLYFIN_DB,
    SET_KEY_MEDIA_LIBRARY_PATH_MAPPINGS,
    SET_KEY_MEDIA_LIBRARY_PREFLIGHT_ENABLED,
    SET_KEY_PATH_ANIME,
    SET_KEY_PATH_AV1_ANIME,
    SET_KEY_PATH_AV1_FILME,
    SET_KEY_PATH_AV1_TV,
    SET_KEY_PATH_FILME,
    SET_KEY_PATH_H264_ANIME,
    SET_KEY_PATH_H264_FILME,
    SET_KEY_PATH_H264_TV,
    SET_KEY_PATH_H265_ANIME,
    SET_KEY_PATH_H265_FILME,
    SET_KEY_PATH_H265_TV,
    SET_KEY_PATH_TV,
)


@dataclass(frozen=True)
class MediaLibraryDialogState:
    enabled: bool
    preflight_enabled: bool
    analyze_on_import: bool
    db_path: str
    jellyfin_db_path: str
    mappings: tuple[PathMapping, ...]


class MediaLibraryDialogService:
    """Fachliche Operationen des Dialogs ohne Qt-UI-Abhängigkeit."""

    def resolve_db_path(self, raw_path: str | None) -> str:
        text = str(raw_path or "").strip()
        return normalize_user_path(text) if text else str(default_media_library_db_path())

    def load_state(self, settings: Any) -> MediaLibraryDialogState:
        mappings = load_path_mappings(settings.value(SET_KEY_MEDIA_LIBRARY_PATH_MAPPINGS, "", type=str))
        if not mappings:
            mappings = self.storage_path_mappings(settings)
        return MediaLibraryDialogState(
            enabled=settings.value(SET_KEY_MEDIA_LIBRARY_ENABLED, DEFAULT_MEDIA_LIBRARY_ENABLED, type=bool),
            preflight_enabled=settings.value(
                SET_KEY_MEDIA_LIBRARY_PREFLIGHT_ENABLED,
                DEFAULT_MEDIA_LIBRARY_PREFLIGHT_ENABLED,
                type=bool,
            ),
            analyze_on_import=settings.value(
                SET_KEY_MEDIA_LIBRARY_ANALYZE_ON_IMPORT,
                DEFAULT_MEDIA_LIBRARY_ANALYZE_ON_IMPORT,
                type=bool,
            ),
            db_path=settings.value(
                SET_KEY_MEDIA_LIBRARY_DB_PATH,
                str(default_media_library_db_path()),
                type=str,
            ),
            jellyfin_db_path=settings.value(SET_KEY_MEDIA_LIBRARY_LAST_JELLYFIN_DB, "", type=str),
            mappings=tuple(mappings),
        )

    def save_state(self, settings: Any, state: MediaLibraryDialogState) -> None:
        settings.setValue(SET_KEY_MEDIA_LIBRARY_ENABLED, state.enabled)
        settings.setValue(SET_KEY_MEDIA_LIBRARY_PREFLIGHT_ENABLED, state.preflight_enabled)
        settings.setValue(SET_KEY_MEDIA_LIBRARY_ANALYZE_ON_IMPORT, state.analyze_on_import)
        settings.setValue(SET_KEY_MEDIA_LIBRARY_DB_PATH, self.resolve_db_path(state.db_path))
        settings.setValue(SET_KEY_MEDIA_LIBRARY_LAST_JELLYFIN_DB, state.jellyfin_db_path.strip())
        settings.setValue(SET_KEY_MEDIA_LIBRARY_PATH_MAPPINGS, dump_path_mappings(state.mappings))
        settings.sync()

    def save_mappings(self, settings: Any, db_path: str, mappings: list[PathMapping]) -> None:
        settings.setValue(SET_KEY_MEDIA_LIBRARY_PATH_MAPPINGS, dump_path_mappings(mappings))
        settings.sync()
        if db_path:
            save_path_mappings(db_path, mappings)

    def create_database(self, db_path: str, mappings: list[PathMapping]) -> Path:
        target = initialize_database(db_path)
        save_path_mappings(target, mappings)
        return target

    def import_jellyfin(
        self,
        jellyfin_db: str,
        db_path: str,
        mappings: list[PathMapping],
        *,
        analyze_existing_files: bool,
        tools: Any,
    ):
        return import_jellyfin_database(
            jellyfin_db,
            db_path,
            mappings,
            analyze_existing_files=analyze_existing_files,
            tools=tools,
        )

    def export_database(self, db_path: str, folder: str):
        return export_database(db_path, folder)

    def export_database_csv(self, db_path: str, folder: str):
        return export_database_to_csv(db_path, folder)

    def export_search_csv(self, rows: list[dict[str, Any]], file_name: str):
        return export_search_results_to_csv(rows, file_name)

    def normalize_stream_types(self, db_path: str) -> int:
        return normalize_database_stream_types(db_path, backup=True)

    def cleanup_inactive_items(self, db_path: str) -> int:
        return cleanup_inactive_media_items(db_path, backup=True)

    def stats(self, db_path: str):
        return get_stats(db_path)

    def search(
        self,
        db_path: str,
        preset: str,
        text: str,
        *,
        scope: str,
        media_type: str,
    ) -> list[dict[str, Any]]:
        return search_library(db_path, preset, text, scope=scope, media_type=media_type)

    def execute_sql(self, db_path: str, sql: str):
        return execute_sql(db_path, sql, backup=True)

    @staticmethod
    def sql_is_mutating(sql: str) -> bool:
        return not sql.strip().casefold().startswith(("select", "pragma", "with"))

    @staticmethod
    def tool_paths(settings: Any):
        return get_tool_paths(settings)

    def storage_scan_roots(self, settings: Any) -> list[PathMapping]:
        entries = (
            ("TV", "/TVSerien", (SET_KEY_PATH_H264_TV, SET_KEY_PATH_H265_TV, SET_KEY_PATH_AV1_TV, SET_KEY_PATH_TV)),
            (
                "Anime",
                "/Anime",
                (SET_KEY_PATH_H264_ANIME, SET_KEY_PATH_H265_ANIME, SET_KEY_PATH_AV1_ANIME, SET_KEY_PATH_ANIME),
            ),
            (
                "Filme",
                "/Filme",
                (SET_KEY_PATH_H264_FILME, SET_KEY_PATH_H265_FILME, SET_KEY_PATH_AV1_FILME, SET_KEY_PATH_FILME),
            ),
        )
        rows: list[PathMapping] = []
        seen: set[str] = set()
        for label, external, keys in entries:
            for key in keys:
                configured = settings.value(key, "", type=str)
                candidate = configured or default_target_path_for_settings_key(key, create=False)
                local = normalize_user_path(candidate)
                if not local or not Path(local).is_dir():
                    continue
                compare = path_compare_key(local)
                if compare in seen:
                    continue
                seen.add(compare)
                rows.append(PathMapping(label, external, local))
        return rows

    @staticmethod
    def storage_path_mappings(settings: Any) -> list[PathMapping]:
        def first_path(*keys: str) -> str:
            for key in keys:
                value = settings.value(key, "", type=str)
                if value:
                    return value
            return ""

        rows = [
            PathMapping("Anime", "/Anime", first_path(SET_KEY_PATH_H265_ANIME, SET_KEY_PATH_ANIME)),
            PathMapping("TV", "/TVSerien", first_path(SET_KEY_PATH_H265_TV, SET_KEY_PATH_TV)),
            PathMapping("Filme", "/Filme", first_path(SET_KEY_PATH_H265_FILME, SET_KEY_PATH_FILME)),
        ]
        return [row for row in rows if row.local_prefix]
