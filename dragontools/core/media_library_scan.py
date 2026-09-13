from __future__ import annotations

import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Iterable

from .media_library_db import _connect, _create_schema, backup_database, initialize_database
from .media_library_paths import save_path_mappings
from .media_library_repository import (
    _fallback_item_from_path, _insert_item, _item_from_media_info,
    _streams_from_media_info_with_sidecars, _subtitle_sidecar_streams,
)
from .media_library_types import DEFAULT_DB_FILENAME, AbortFn, LibraryScanResult, LogFn, PathMapping, ProgressFn, _now
from .media_library_utils import _normalize_title
from .models import MediaInfo
from .paths import VIDEO_EXTENSIONS, normalize_user_path, path_compare_key

_SCAN_SKIP_DIRS = {
    "__temp_overwrite__", ".grab", ".sync", ".stfolder", ".stversions", "@eadir",
    "bdmv", "certificate", "lost+found",
}

def _scan_video_files(roots: Iterable[PathMapping]) -> tuple[list[tuple[Path, str]], list[str], int]:
    files: list[tuple[Path, str]] = []
    warnings: list[str] = []
    skipped_roots = 0
    seen_roots: set[str] = set()
    seen_files: set[str] = set()

    for root in roots:
        local = normalize_user_path(root.local_prefix)
        if not local:
            continue
        key = path_compare_key(local)
        if key in seen_roots:
            continue
        seen_roots.add(key)
        root_path = Path(local)
        if not root_path.is_dir():
            skipped_roots += 1
            warnings.append(f"Scan-Ordner nicht erreichbar: {root.label or local} -> {local}")
            continue
        for current, dirs, names in os.walk(root_path):
            dirs[:] = [
                name for name in dirs
                if name.casefold() not in _SCAN_SKIP_DIRS and not name.startswith(".")
            ]
            for name in names:
                path = Path(current) / name
                if path.suffix.casefold() not in VIDEO_EXTENSIONS:
                    continue
                file_key = path_compare_key(path)
                if file_key in seen_files:
                    continue
                seen_files.add(file_key)
                files.append((path, root.label or ""))
    files.sort(key=lambda entry: path_compare_key(entry[0]))
    return files, warnings, skipped_roots


def _year_from_text(text: str | None) -> int | None:
    import re

    match = re.search(r"\b(19\d{2}|20\d{2})\b", text or "")
    return int(match.group(1)) if match else None


def _strip_year_suffix(text: str | None) -> str:
    import re

    cleaned = re.sub(r"\s*\((?:19|20)\d{2}\)\s*$", "", text or "").strip()
    return cleaned or (text or "").strip()


def _season_number_from_folder(name: str) -> int | None:
    import re

    match = re.search(r"(?:staffel|season|saison)\s*(\d+)", name or "", re.IGNORECASE)
    return int(match.group(1)) if match else None


def _is_season_folder(path: Path) -> bool:
    name = path.name.casefold()
    return name.startswith(("staffel", "season", "saison", "special", "extras"))


def _folder_item(
    *,
    item_type: str,
    title: str,
    path: Path,
    source: str,
    series_title: str | None = None,
    season: int | None = None,
    year: int | None = None,
) -> dict[str, Any]:
    return {
        "item_type": item_type,
        "title": title,
        "series_title": series_title,
        "season": season,
        "episode": None,
        "year": year,
        "source": source,
        "source_id": None,
        "provider": None,
        "path": str(path),
        "parent_path": str(path.parent),
        "filename": path.name,
        "normalized_title": _normalize_title(series_title or title),
        "container": "",
        "duration_s": None,
        "size_bytes": None,
        "width": None,
        "height": None,
        "video_codec": None,
        "video_bitrate": None,
        "overall_bitrate": None,
        "is_hdr": 0,
        "has_hdr10plus": 0,
        "has_dolby_vision": 0,
        "dv_profile": None,
        "nfo_status": "unknown",
        "trickplay_status": "unknown",
        "analysis_status": "folder",
        "exists_flag": 1,
        "active": 1,
    }


def _apply_storage_scan_context(item: dict[str, Any], file_path: Path, area_label: str) -> None:
    area = (area_label or "").casefold()
    if "film" in area or "movie" in area:
        if item.get("item_type") != "episode":
            item["item_type"] = "movie"
        item["year"] = item.get("year") or _year_from_text(file_path.stem) or _year_from_text(file_path.parent.name)
        item["normalized_title"] = _normalize_title(item.get("title"))
        return

    if item.get("item_type") != "episode":
        return

    parent = file_path.parent
    series_root = parent.parent if _is_season_folder(parent) else parent
    series_title = item.get("series_title") or _strip_year_suffix(series_root.name)
    item["series_title"] = series_title
    item["year"] = item.get("year") or _year_from_text(series_root.name)
    if item.get("season") is None and _is_season_folder(parent):
        item["season"] = _season_number_from_folder(parent.name)
    item["normalized_title"] = _normalize_title(series_title)


def _insert_storage_scan_hierarchy(conn: sqlite3.Connection, item: dict[str, Any], file_path: Path, area_label: str) -> int:
    inserted = 0
    if item.get("item_type") != "episode" or not item.get("series_title"):
        return inserted

    parent = file_path.parent
    series_root = parent.parent if _is_season_folder(parent) else parent
    series_title = str(item.get("series_title") or _strip_year_suffix(series_root.name))
    year = item.get("year") or _year_from_text(series_root.name)
    _insert_item(
        conn,
        _folder_item(
            item_type="series",
            title=series_title,
            series_title=series_title,
            path=series_root,
            source="storage_scan",
            year=year,
        ),
        [],
    )
    inserted += 1

    if _is_season_folder(parent):
        season = item.get("season") or _season_number_from_folder(parent.name)
        _insert_item(
            conn,
            _folder_item(
                item_type="season",
                title=parent.name,
                series_title=series_title,
                season=season,
                path=parent,
                source="storage_scan",
                year=year,
            ),
            [],
        )
        inserted += 1
    return inserted


def scan_storage_paths_to_database(
    target_db_path: str | Path,
    scan_roots: Iterable[PathMapping],
    *,
    tools: Any = None,
    replace_existing: bool = True,
    logger: LogFn = None,
    progress: ProgressFn = None,
    should_abort: AbortFn = None,
    analyzer: Callable[[str, Any], MediaInfo] | None = None,
) -> LibraryScanResult:
    """Build or update the DragonTools library by scanning real media files.

    MediaInfo remains the primary source through ``analyze_media``. ffprobe is
    still used by the analyzer as a supplemental index/fallback source.
    """
    from .media_analyzer import analyze_media

    target = Path(target_db_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    roots = [root for root in scan_roots if str(root.local_prefix or "").strip()]
    files, warnings, skipped_roots = _scan_video_files(roots)
    total = len(files)
    if logger:
        logger(f"Mediathek-Scan: {total} Videodatei(en) in {len(roots)} Speicherpfad(en) gefunden.")

    analyze_fn = analyzer or analyze_media
    imported_items = 0
    imported_streams = 0
    failed_files = 0
    hierarchy_items = 0
    aborted = False

    if replace_existing:
        tmp_context = tempfile.TemporaryDirectory(prefix="dragontools_storage_scan_", dir=str(target.parent))
        tmp_dir = Path(tmp_context.name)
        work_db = tmp_dir / DEFAULT_DB_FILENAME
    else:
        tmp_context = None
        work_db = target

    try:
        initialize_database(work_db)
        if roots:
            save_path_mappings(work_db, roots)
        with closing(_connect(work_db)) as conn:
            with conn:
                for index, (path_obj, area_label) in enumerate(files, start=1):
                    if should_abort and should_abort():
                        aborted = True
                        break
                    if progress:
                        progress(index, total, str(path_obj))
                    try:
                        info = analyze_fn(str(path_obj), tools)
                        item = _item_from_media_info(path_obj, info, source="storage_scan")
                        _apply_storage_scan_context(item, path_obj, area_label)
                        streams = _streams_from_media_info_with_sidecars(path_obj, info)
                        hierarchy_items += _insert_storage_scan_hierarchy(conn, item, path_obj, area_label)
                        _insert_item(conn, item, streams)
                        imported_items += 1
                        imported_streams += len(streams)
                    except Exception as exc:
                        failed_files += 1
                        warnings.append(f"Analyse fehlgeschlagen: {path_obj.name}: {exc}")
                        if logger:
                            logger(f"Warnung: {path_obj.name} konnte nicht analysiert werden: {exc}")
                        item = _fallback_item_from_path(path_obj, source="storage_scan")
                        _apply_storage_scan_context(item, path_obj, area_label)
                        hierarchy_items += _insert_storage_scan_hierarchy(conn, item, path_obj, area_label)
                        streams = _subtitle_sidecar_streams(path_obj)
                        _insert_item(conn, item, streams)
                        imported_items += 1
                        imported_streams += len(streams)
                conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('updated_at', ?)", (_now(),))

        if aborted:
            if logger:
                logger("Mediathek-Scan abgebrochen. Die vorhandene Datenbank wurde nicht ersetzt.")
            return LibraryScanResult(
                target,
                total,
                imported_items + hierarchy_items,
                imported_streams,
                failed_files,
                skipped_roots,
                True,
                tuple(warnings),
            )

        if replace_existing:
            if target.exists():
                backup_database(target, "pre_storage_scan")
            os.replace(work_db, target)

        if logger:
            logger(
                "Mediathek-Scan abgeschlossen: "
                f"{imported_items} Videodatei(en), {hierarchy_items} Serien-/Staffel-Einträge, "
                f"{imported_streams} Stream(s), {failed_files} Fehler."
            )
        return LibraryScanResult(
            target,
            total,
            imported_items + hierarchy_items,
            imported_streams,
            failed_files,
            skipped_roots,
            False,
            tuple(warnings),
        )
    finally:
        if tmp_context is not None:
            tmp_context.cleanup()
