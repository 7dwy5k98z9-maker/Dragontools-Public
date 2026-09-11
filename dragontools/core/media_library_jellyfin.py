from __future__ import annotations

import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable

from .media_library_db import (
    _connect,
    _create_schema,
    _snapshot_database,
    _table_columns,
    _table_names,
    backup_database,
    initialize_database,
)
from .media_library_paths import _matches_any_mapping_prefix, apply_path_mappings, save_path_mappings
from .media_library_jellyfin_metadata import (
    apply_auxiliary_metadata,
    apply_collection_metadata,
    load_jellyfin_auxiliary_metadata,
)
from .media_library_repository import _insert_item, _item_from_media_info, _streams_from_media_info
from .media_library_types import DEFAULT_DB_FILENAME, LibraryImportResult, LogFn, PathMapping, _now
from .media_library_utils import (
    _bool, _float_or_none, _infer_item_type, _int_or_none, _normalize_stream_type,
    _normalize_title, _safe_parent,
)
from .paths import VIDEO_EXTENSIONS, path_compare_key


_IMPORTABLE_JELLYFIN_ITEM_TYPES = {"movie", "series", "season", "episode", "video"}
_HDR_MARKERS = (
    "hdr",
    "bt2020",
    "pq",
    "hlg",
    "dolby",
    "dovi",
    "dvhe",
    "smpte2084",
    "st2084",
    "arib-std-b67",
    "2094-40",
    "st2094",
)

def _column_map(cursor: sqlite3.Cursor) -> dict[str, str]:
    return {desc[0].casefold(): desc[0] for desc in cursor.description or []}


def _row_value(row: sqlite3.Row, columns: dict[str, str], *names: str, default: Any = None) -> Any:
    for name in names:
        col = columns.get(name.casefold())
        if col is not None:
            return row[col]
    return default


def _pick_jellyfin_item_table(conn: sqlite3.Connection) -> str | None:
    tables = _table_names(conn)
    for candidate in ("TypedBaseItems", "BaseItems", "MediaItems"):
        if candidate in tables:
            columns = _table_columns(conn, candidate)
            if "path" in columns or "name" in columns:
                return candidate
    for table in tables:
        columns = _table_columns(conn, table)
        if "path" in columns and ("name" in columns or "originaltitle" in columns):
            return table
    return None


def _pick_jellyfin_stream_table(conn: sqlite3.Connection) -> str | None:
    tables = _table_names(conn)
    for candidate in ("MediaStreamInfos", "MediaStreams", "mediastreams"):
        if candidate in tables:
            return candidate
    for table in tables:
        columns = _table_columns(conn, table)
        if "streamtype" in columns and "itemid" in columns:
            return table
    return None


def _pick_jellyfin_trickplay_table(conn: sqlite3.Connection) -> str | None:
    tables = _table_names(conn)
    for candidate in ("TrickplayInfos", "TrickplayInfo", "trickplayinfos"):
        if candidate in tables:
            return candidate
    for table in tables:
        columns = _table_columns(conn, table)
        if "itemid" in columns and "thumbnailcount" in columns:
            return table
    return None


def _infer_jellyfin_item_type(type_text: str, path: str) -> str:
    """Map Jellyfin's explicit entity type without guessing Movie/Episode from the path.

    Jellyfin type strings are usually fully-qualified class names such as
    ``MediaBrowser.Controller.Entities.Movies.Movie``.  Looking for the substring
    ``movie`` is unsafe because the namespace ``...Entities.Movies.*`` also contains
    non-movie entities (for example BoxSet).  Likewise, generic Jellyfin video
    entities must not become episodes merely because their filename happens to match
    SxxExx.

    Path-based Movie/Episode inference remains available in ``_infer_item_type`` for
    local DragonTools scans where no authoritative external type exists.
    """
    raw = str(type_text or "").strip()
    # Be tolerant of assembly-qualified .NET type strings.
    qualified = raw.split(",", 1)[0].strip()
    leaf = qualified.rsplit(".", 1)[-1].casefold() if qualified else ""

    explicit = {
        "episode": "episode",
        "series": "series",
        "season": "season",
        "movie": "movie",
        "film": "movie",
        "video": "video",
        "musicvideo": "video",
        "trailer": "video",
        "boxset": "folder",
        "collectionfolder": "folder",
        "aggregatefolder": "folder",
        "userrootfolder": "folder",
        "folder": "folder",
    }
    if leaf in explicit:
        return explicit[leaf]

    # Unknown *typed* Jellyfin entities stay neutral. A video file is searchable as
    # generic video, but it is deliberately not counted as Movie/Episode.
    if qualified:
        return "video" if Path(path).suffix.casefold() in VIDEO_EXTENSIONS else "folder"

    # Very old/minimal schemas may genuinely have no type value. Only in that case
    # keep the legacy local heuristic as a compatibility fallback.
    return _infer_item_type("", path)


def _is_importable_jellyfin_item(item_type: str, path: str) -> bool:
    """Begrenzt den Bestand auf funktionale Medien- und Hierarchieeintraege.

    Moderne Jellyfin-Datenbanken enthalten auch Personen, Studios, Genres,
    Sammlungen und Playlists mit Metadatenpfaden. Diese Objekte gehoeren nicht
    in die DragonTools-Mediathek. Generische Videoobjekte werden nur uebernommen,
    wenn ihr Pfad auf eine von DragonTools unterstuetzte Videodatei zeigt.
    """
    if item_type not in _IMPORTABLE_JELLYFIN_ITEM_TYPES:
        return False
    if item_type == "video":
        return Path(path).suffix.casefold() in VIDEO_EXTENSIONS
    return True


def _validate_jellyfin_snapshot(conn: sqlite3.Connection) -> None:
    """Verhindert einen Import aus einer unvollstaendigen DB-/WAL-Kopie."""
    row = conn.execute("PRAGMA quick_check(1)").fetchone()
    result = str(row[0] if row else "").strip()
    if result.casefold() != "ok":
        detail = result or "unbekannter SQLite-Konsistenzfehler"
        raise RuntimeError(f"Jellyfin-Datenbank ist nicht konsistent: {detail}")


def _is_stream_dict_type(stream: dict[str, Any], expected: str) -> bool:
    return (
        _normalize_stream_type(
            stream.get("stream_type"),
            codec=stream.get("codec"),
            channels=stream.get("channels"),
            width=stream.get("width"),
            height=stream.get("height"),
        ).casefold()
        == expected.casefold()
    )


def _video_flags_from_streams(streams: list[dict[str, Any]]) -> tuple[int, int, int, str | None, int | None, int | None, str | None, int | None]:
    video = next((stream for stream in streams if _is_stream_dict_type(stream, "video")), {})
    text = " ".join(str(video.get(key) or "") for key in ("hdr_format", "codec", "pix_fmt", "title", "dv_profile")).casefold()
    dv_profile = _int_or_none(video.get("dv_profile"))
    has_hdr10plus = 1 if (
        _bool(video.get("hdr10plus_present"))
        or any(marker in text for marker in ("hdr10+", "hdr10plus", "dynamic metadata", "2094-40", "st2094"))
    ) else 0
    has_dv = 1 if (
        _bool(video.get("rpu_present"))
        or (dv_profile is not None and dv_profile > 0)
        or any(marker in text for marker in ("dolby vision", "dovi", "dvhe", "dolbyvision"))
    ) else 0
    is_hdr = 1 if has_hdr10plus or has_dv or any(marker in text for marker in _HDR_MARKERS) else 0
    return (
        is_hdr,
        has_hdr10plus,
        has_dv,
        video.get("dv_profile"),
        _int_or_none(video.get("width")),
        _int_or_none(video.get("height")),
        video.get("codec"),
        _int_or_none(video.get("bitrate")),
    )


def _jellyfin_hdr_format(row: sqlite3.Row, columns: dict[str, str]) -> str:
    parts: list[str] = []
    for name in (
        "VideoRange",
        "VideoRangeType",
        "ColorPrimaries",
        "ColorSpace",
        "ColorTransfer",
        "TransferCharacteristics",
        "HDR_Format",
        "HDR_Format_String",
        "HDR_Format_Commercial",
        "HDR_Format_Compatibility",
        "HdrFormat",
        "HdrFormatString",
    ):
        value = _row_value(row, columns, name, default=None)
        if value not in (None, ""):
            parts.append(str(value))

    for key, column in columns.items():
        normalized = key.replace("_", "").replace("-", "").casefold()
        if "hdr10plus" not in normalized and "hdr10+" not in normalized:
            continue
        value = row[column]
        text = str(value or "").strip().casefold()
        if _bool(value) or any(marker in text for marker in ("hdr10+", "hdr10plus", "2094-40", "true", "yes", "ja")):
            parts.append("hdr10plus")

    rpu_present = _bool(_row_value(row, columns, "RpuPresentFlag", default=0))
    dv_profile = _int_or_none(_row_value(row, columns, "DvProfile", "DolbyVisionProfile", default=None))
    if rpu_present or (dv_profile is not None and dv_profile > 0):
        parts.append("Dolby Vision")

    return " | ".join(dict.fromkeys(parts))


def _stream_from_jellyfin_row(row: sqlite3.Row, columns: dict[str, str]) -> dict[str, Any]:
    raw_stream_type = _row_value(row, columns, "StreamType", "type", default="")
    codec = _row_value(row, columns, "Codec", default=None)
    channels = _int_or_none(_row_value(row, columns, "Channels", default=None))
    width = _int_or_none(_row_value(row, columns, "Width", default=None))
    height = _int_or_none(_row_value(row, columns, "Height", default=None))
    stream_type = _normalize_stream_type(
        raw_stream_type,
        codec=codec,
        channels=channels,
        width=width,
        height=height,
    )
    video_range = _jellyfin_hdr_format(row, columns)
    if stream_type.casefold() == "video" and not any(marker in video_range.casefold() for marker in _HDR_MARKERS):
        video_range = " | ".join(part for part in (video_range, "SDR") if part)
    dv_profile = _row_value(row, columns, "DvProfile", "DolbyVisionProfile", "Profile", default=None)
    pix_fmt = _row_value(row, columns, "PixelFormat", "PixFmt", default=None)
    bit_depth = _row_value(row, columns, "BitDepth", default=None)
    average_frame_rate = _float_or_none(
        _row_value(row, columns, "AverageFrameRate", "AvgFrameRate", default=None)
    )
    real_frame_rate = _float_or_none(
        _row_value(row, columns, "RealFrameRate", "FrameRate", default=None)
    )
    frame_rate = average_frame_rate or real_frame_rate
    frame_rate_mode = None
    if average_frame_rate and real_frame_rate:
        frame_rate_mode = "CFR" if abs(average_frame_rate - real_frame_rate) <= 0.001 else "VFR"
    external_path = _row_value(row, columns, "Path", "ExternalPath", "FilePath", default=None)
    is_external_subtitle = stream_type.casefold() == "subtitle" and (
        _bool(_row_value(row, columns, "IsExternal", "External", "IsExternalSubtitle", default=0))
        or bool(external_path)
    )
    return {
        "stream_type": stream_type,
        "stream_index": _int_or_none(_row_value(row, columns, "Index", "StreamIndex", default=None)),
        "codec": codec,
        "language": _row_value(row, columns, "Language", default=None),
        "forced": _bool(_row_value(row, columns, "IsForced", "IsForcedSubtitle", default=0)),
        "channels": channels,
        "channel_layout": _row_value(row, columns, "ChannelLayout", default=None),
        "bitrate": _int_or_none(_row_value(row, columns, "BitRate", "Bitrate", default=None)),
        "width": width,
        "height": height,
        "hdr_format": video_range,
        "dv_profile": dv_profile,
        "pix_fmt": pix_fmt,
        "bit_depth": _int_or_none(bit_depth),
        "profile": _row_value(row, columns, "Profile", default=None),
        "duration_s": None,
        "frame_count": None,
        "frame_rate": str(frame_rate) if frame_rate is not None else None,
        "frame_rate_mode": frame_rate_mode,
        "color_space": _row_value(row, columns, "ColorSpace", default=None),
        "color_transfer": _row_value(
            row, columns, "ColorTransfer", "TransferCharacteristics", default=None
        ),
        "color_primaries": _row_value(row, columns, "ColorPrimaries", default=None),
        "source_kind": "external" if is_external_subtitle else "internal",
        "external_path": external_path if is_external_subtitle else None,
        "title": _row_value(row, columns, "Title", "DisplayTitle", default=None),
        "rpu_present": _bool(_row_value(row, columns, "RpuPresentFlag", default=0)),
        "hdr10plus_present": _bool(_row_value(row, columns, "Hdr10PlusPresentFlag", default=0)),
    }


def _trickplay_status_by_item(conn: sqlite3.Connection, table: str) -> dict[str, str]:
    columns = _table_columns(conn, table)
    item_col = columns.get("itemid") or columns.get("item_id") or columns.get("mediacontainerid")
    if not item_col:
        return {}
    cur = conn.execute(f"SELECT * FROM {table}")
    row_columns = _column_map(cur)
    statuses: dict[str, str] = {}
    for row in cur.fetchall():
        item_id = str(row[item_col] or "").casefold()
        if not item_id:
            continue
        thumbnail_count = _int_or_none(
            _row_value(row, row_columns, "ThumbnailCount", "Count", "ImageCount", default=None)
        )
        status = "empty" if thumbnail_count is not None and thumbnail_count <= 0 else "present"
        if statuses.get(item_id) != "present":
            statuses[item_id] = status
    return statuses


def _jellyfin_duration_seconds(row: sqlite3.Row, columns: dict[str, str]) -> float | None:
    """Konvertiert Jellyfin-Ticks eindeutig, ohne lange Sekundenwerte zu verfälschen."""
    ticks_column = columns.get("runtimeticks")
    if ticks_column:
        ticks = _float_or_none(row[ticks_column])
        return ticks / 10_000_000.0 if ticks is not None else None
    return _float_or_none(_row_value(row, columns, "DurationSeconds", default=None))


def _group_streams_by_item(conn: sqlite3.Connection, table: str) -> dict[str, list[dict[str, Any]]]:
    columns = _table_columns(conn, table)
    item_col = columns.get("itemid") or columns.get("item_id") or columns.get("mediacontainerid")
    if not item_col:
        return {}
    cur = conn.execute(f"SELECT * FROM {table}")
    row_columns = _column_map(cur)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in cur.fetchall():
        item_id = str(row[item_col] or "").casefold()
        if not item_id:
            continue
        grouped.setdefault(item_id, []).append(_stream_from_jellyfin_row(row, row_columns))
    return grouped


def _jellyfin_item_id(row: sqlite3.Row, columns: dict[str, str]) -> str:
    return str(
        _row_value(row, columns, "Guid", "Id", "ItemId", "InternalId", "UserDataKey", default="")
        or ""
    ).casefold()


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
    imported_items = 0
    imported_streams = 0
    skipped_items = 0

    if target.exists():
        backup_database(target, "pre_import")

    # Das Temp-Verzeichnis liegt absichtlich direkt am Ziel. Dadurch befinden
    # sich staging DB und finales Ziel auch unter Windows/UNC auf demselben
    # Volume und der abschliessende os.replace() bleibt atomar moeglich.
    with tempfile.TemporaryDirectory(
        prefix="dragontools_jellyfin_import_",
        dir=str(target.parent),
    ) as tmp:
        tmp_dir = Path(tmp)
        source_copy = tmp_dir / source.name
        # Aktive Jellyfin-DBs koennen commitete Seiten noch im WAL halten. Eine
        # rohe Dateikopie ist deshalb unvollstaendig. Der read-only Online-Backup
        # Snapshot liest DB + WAL konsistent und veraendert das Original nicht.
        _snapshot_database(source, source_copy, source_read_only=True)
        tmp_db = tmp_dir / DEFAULT_DB_FILENAME
        initialize_database(tmp_db)
        if mappings_list:
            save_path_mappings(tmp_db, mappings_list)

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
            trickplay_by_item = (
                _trickplay_status_by_item(source_conn, trickplay_table) if trickplay_table else {}
            )

            item_cur = source_conn.execute(f"SELECT * FROM {item_table}")
            item_columns = _column_map(item_cur)
            rows = item_cur.fetchall()
            auxiliary_metadata = load_jellyfin_auxiliary_metadata(
                source_conn, item_table, rows, item_columns
            )
            item_names_by_id = {
                _jellyfin_item_id(row, item_columns): str(
                    _row_value(row, item_columns, "Name", "OriginalTitle", "SortName", default="") or ""
                )
                for row in rows
                if _jellyfin_item_id(row, item_columns)
            }
        finally:
            source_conn.close()

        with closing(_connect(tmp_db)) as target_conn:
            with target_conn:
                _create_schema(target_conn)
                seen_paths: set[str] = set()
                source_to_media_id: dict[str, int] = {}
                for row in rows:
                    raw_path = str(_row_value(row, item_columns, "Path", default="") or "")
                    name = str(_row_value(row, item_columns, "Name", "OriginalTitle", "SortName", default="") or "")
                    if not raw_path and not name:
                        skipped_items += 1
                        continue
                    if raw_path and mappings_list and not _matches_any_mapping_prefix(raw_path, mappings_list):
                        skipped_items += 1
                        continue
                    mapped_path = apply_path_mappings(raw_path, mappings_list) if raw_path else ""
                    if not mapped_path:
                        skipped_items += 1
                        continue
                    source_id = _jellyfin_item_id(row, item_columns)
                    raw_type = str(_row_value(row, item_columns, "Type", "type", default="") or "")
                    item_type = _infer_jellyfin_item_type(raw_type, mapped_path)
                    if not _is_importable_jellyfin_item(item_type, mapped_path):
                        skipped_items += 1
                        continue
                    path_key = path_compare_key(mapped_path)
                    if path_key in seen_paths:
                        skipped_items += 1
                        continue
                    seen_paths.add(path_key)
                    streams = [dict(stream) for stream in streams_by_item.get(source_id, [])]
                    for stream in streams:
                        external_path = str(stream.get("external_path") or "").strip()
                        if external_path and mappings_list:
                            stream["external_path"] = apply_path_mappings(external_path, mappings_list)
                    is_hdr, has_hdr10plus, has_dv, dv_profile, width, height, video_codec, video_bitrate = (
                        _video_flags_from_streams(streams)
                    )
                    path_obj = Path(mapped_path)
                    series_title = str(_row_value(row, item_columns, "SeriesName", default="") or "").strip()
                    if item_type == "series":
                        series_title = name or series_title
                    elif not series_title:
                        series_id = str(_row_value(row, item_columns, "SeriesId", default="") or "").casefold()
                        series_title = item_names_by_id.get(series_id, "")
                    if item_type == "season":
                        season_number = _int_or_none(
                            _row_value(row, item_columns, "IndexNumber", "SeasonNumber", default=None)
                        )
                    else:
                        season_number = _int_or_none(
                            _row_value(row, item_columns, "ParentIndexNumber", "SeasonNumber", default=None)
                        )
                    jellyfin_size_bytes = _int_or_none(
                        _row_value(row, item_columns, "Size", "FileSize", default=None)
                    )
                    if not jellyfin_size_bytes or jellyfin_size_bytes <= 0:
                        try:
                            if path_obj.is_file():
                                jellyfin_size_bytes = int(path_obj.stat().st_size)
                        except OSError:
                            pass

                    item = {
                        "item_type": item_type,
                        "title": name or path_obj.stem,
                        "original_title": str(
                            _row_value(row, item_columns, "OriginalTitle", default="") or ""
                        ).strip() or None,
                        "series_title": series_title or None,
                        "season": season_number,
                        "episode": _int_or_none(
                            _row_value(row, item_columns, "IndexNumber", "EpisodeNumber", default=None)
                        ) if item_type == "episode" else None,
                        "year": _int_or_none(
                            _row_value(row, item_columns, "ProductionYear", "PremiereDate", "Year", default=None)
                        ),
                        "source": "jellyfin",
                        "source_id": source_id or None,
                        "provider": None,
                        "path": mapped_path,
                        "parent_path": _safe_parent(mapped_path),
                        "filename": path_obj.name,
                        "normalized_title": _normalize_title(
                            str(_row_value(row, item_columns, "SeriesName", default="") or name or path_obj.stem)
                        ),
                        "container": path_obj.suffix.lstrip(".").lower(),
                        "duration_s": _jellyfin_duration_seconds(row, item_columns),
                        "size_bytes": jellyfin_size_bytes,
                        "width": width,
                        "height": height,
                        "video_codec": video_codec,
                        "video_bitrate": video_bitrate,
                        "overall_bitrate": _int_or_none(
                            _row_value(row, item_columns, "TotalBitrate", "OverallBitrate", default=None)
                        ),
                        "is_hdr": is_hdr,
                        "has_hdr10plus": has_hdr10plus,
                        "has_dolby_vision": has_dv,
                        "dv_profile": dv_profile,
                        "nfo_status": "unknown",
                        "trickplay_status": trickplay_by_item.get(
                            source_id,
                            "missing" if trickplay_table and item_type in {"movie", "episode", "video"} else "unknown",
                        ),
                        "analysis_status": "jellyfin",
                        "exists_flag": 1,
                        "active": 1,
                    }
                    if analyze_existing_files and path_obj.suffix.casefold() in VIDEO_EXTENSIONS and path_obj.exists():
                        try:
                            from .media_analyzer import analyze_media

                            info = analyze_media(str(path_obj), tools=tools)
                            item.update(_item_from_media_info(path_obj, info, source="jellyfin+scan"))
                            streams = _streams_from_media_info(info)
                        except Exception as exc:
                            warnings.append(f"Analyse fehlgeschlagen: {path_obj.name}: {exc}")
                    imported_streams += len(streams)
                    media_id = _insert_item(target_conn, item, streams)
                    if source_id:
                        source_to_media_id[source_id] = media_id
                        apply_auxiliary_metadata(target_conn, media_id, source_id, auxiliary_metadata)
                    imported_items += 1
                apply_collection_metadata(target_conn, source_to_media_id, auxiliary_metadata)
                target_conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('updated_at', ?)", (_now(),))

        # Auch die neu aufgebaute DragonTools-DB laeuft im WAL-Modus. Vor dem
        # atomaren Austausch deshalb nochmals einen eigenstaendigen Snapshot
        # erzeugen, damit keine commiteten Seiten in einer Temp-WAL zurueckbleiben.
        replacement_db = tmp_dir / f".{DEFAULT_DB_FILENAME}.ready"
        _snapshot_database(tmp_db, replacement_db)
        os.replace(replacement_db, target)
    if logger:
        logger(f"Mediathek-DB importiert: {imported_items} Einträge, {imported_streams} Streams.")
    return LibraryImportResult(target, imported_items, imported_streams, skipped_items, tuple(warnings))
