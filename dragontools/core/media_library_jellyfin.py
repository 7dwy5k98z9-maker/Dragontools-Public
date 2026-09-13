from __future__ import annotations

import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable

from .media_library_db import _connect, _snapshot_database, backup_database, initialize_database
from .media_library_jellyfin_items import build_jellyfin_item
from .media_library_jellyfin_metadata import (
    apply_auxiliary_metadata,
    apply_collection_metadata,
    load_jellyfin_auxiliary_metadata,
)
from .media_library_jellyfin_source import (
    _column_map,
    _infer_jellyfin_item_type,
    _is_importable_jellyfin_item,
    _jellyfin_duration_seconds,
    _jellyfin_item_id,
    _pick_jellyfin_item_table,
    _pick_jellyfin_stream_table,
    _pick_jellyfin_trickplay_table,
    _row_value,
    _validate_jellyfin_snapshot,
)
from .media_library_jellyfin_streams import (
    _group_streams_by_item,
    _jellyfin_hdr_format,
    _stream_from_jellyfin_row,
    _trickplay_status_by_item,
    _video_flags_from_streams,
)
from .media_library_paths import save_path_mappings
from .media_library_repository import _insert_item
from .media_library_types import DEFAULT_DB_FILENAME, LibraryImportResult, LogFn, PathMapping, _now


def _load_source_snapshot(
    source_copy: Path,
    warnings: list[str],
):
    source_conn = sqlite3.connect(str(source_copy))
    source_conn.row_factory = sqlite3.Row
    try:
        _validate_jellyfin_snapshot(source_conn)
        item_table = _pick_jellyfin_item_table(source_conn)
        if not item_table:
            raise RuntimeError("Keine passende Jellyfin-Medientabelle gefunden.")

        stream_table = _pick_jellyfin_stream_table(source_conn)
        streams_by_item = _group_streams_by_item(source_conn, stream_table) if stream_table else {}
        if not stream_table:
            warnings.append("Keine MediaStreams-Tabelle gefunden. Streamdetails werden nur bei Analyse ergänzt.")

        trickplay_table = _pick_jellyfin_trickplay_table(source_conn)
        trickplay_by_item = _trickplay_status_by_item(source_conn, trickplay_table) if trickplay_table else {}

        item_cur = source_conn.execute(f"SELECT * FROM {item_table}")
        item_columns = _column_map(item_cur)
        rows = item_cur.fetchall()
        auxiliary_metadata = load_jellyfin_auxiliary_metadata(source_conn, item_table, rows, item_columns)
        item_names_by_id = {
            _jellyfin_item_id(row, item_columns): str(
                _row_value(row, item_columns, "Name", "OriginalTitle", "SortName", default="") or ""
            )
            for row in rows
            if _jellyfin_item_id(row, item_columns)
        }
        return (
            rows,
            item_columns,
            streams_by_item,
            trickplay_by_item,
            trickplay_table is not None,
            auxiliary_metadata,
            item_names_by_id,
        )
    finally:
        source_conn.close()


def _import_rows(
    target_db: Path,
    rows,
    item_columns: dict[str, str],
    *,
    mappings: list[PathMapping],
    streams_by_item,
    trickplay_by_item,
    has_trickplay_table: bool,
    auxiliary_metadata,
    item_names_by_id: dict[str, str],
    analyze_existing_files: bool,
    tools: Any,
    warnings: list[str],
) -> tuple[int, int, int]:
    imported_items = 0
    imported_streams = 0
    skipped_items = 0
    with closing(_connect(target_db)) as target_conn, target_conn:
        seen_paths: set[str] = set()
        source_to_media_id: dict[str, int] = {}
        for row in rows:
            built = build_jellyfin_item(
                row,
                item_columns,
                mappings=mappings,
                item_names_by_id=item_names_by_id,
                streams_by_item=streams_by_item,
                trickplay_by_item=trickplay_by_item,
                has_trickplay_table=has_trickplay_table,
                seen_paths=seen_paths,
                analyze_existing_files=analyze_existing_files,
                tools=tools,
                warnings=warnings,
            )
            if built is None:
                skipped_items += 1
                continue
            item, streams, source_id = built
            imported_streams += len(streams)
            media_id = _insert_item(target_conn, item, streams)
            if source_id:
                source_to_media_id[source_id] = media_id
                apply_auxiliary_metadata(target_conn, media_id, source_id, auxiliary_metadata)
            imported_items += 1
        apply_collection_metadata(target_conn, source_to_media_id, auxiliary_metadata)
        target_conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('updated_at', ?)", (_now(),))
    return imported_items, imported_streams, skipped_items


def import_jellyfin_database(
    jellyfin_db_path: str | Path,
    target_db_path: str | Path,
    mappings: Iterable[PathMapping] = (),
    *,
    analyze_existing_files: bool = False,
    tools: Any = None,
    logger: LogFn = None,
) -> LibraryImportResult:
    source = Path(jellyfin_db_path)
    if not source.exists():
        raise FileNotFoundError(f"Jellyfin-Datenbank nicht gefunden: {source}")
    target = Path(target_db_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    mappings_list = list(mappings)
    warnings: list[str] = []

    if target.exists():
        backup_database(target, "pre_import")

    with tempfile.TemporaryDirectory(prefix="dragontools_jellyfin_import_", dir=str(target.parent)) as tmp:
        tmp_dir = Path(tmp)
        source_copy = tmp_dir / source.name
        _snapshot_database(source, source_copy, source_read_only=True)
        tmp_db = tmp_dir / DEFAULT_DB_FILENAME
        initialize_database(tmp_db)
        if mappings_list:
            save_path_mappings(tmp_db, mappings_list)

        source_data = _load_source_snapshot(source_copy, warnings)
        imported_items, imported_streams, skipped_items = _import_rows(
            tmp_db,
            source_data[0],
            source_data[1],
            mappings=mappings_list,
            streams_by_item=source_data[2],
            trickplay_by_item=source_data[3],
            has_trickplay_table=source_data[4],
            auxiliary_metadata=source_data[5],
            item_names_by_id=source_data[6],
            analyze_existing_files=analyze_existing_files,
            tools=tools,
            warnings=warnings,
        )

        replacement_db = tmp_dir / f".{DEFAULT_DB_FILENAME}.ready"
        _snapshot_database(tmp_db, replacement_db)
        os.replace(replacement_db, target)

    if logger:
        logger(f"Mediathek-DB importiert: {imported_items} Einträge, {imported_streams} Streams.")
    return LibraryImportResult(target, imported_items, imported_streams, skipped_items, tuple(warnings))


__all__ = ["import_jellyfin_database"]
