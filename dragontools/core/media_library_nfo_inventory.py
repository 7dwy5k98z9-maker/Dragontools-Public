from __future__ import annotations

import sqlite3
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .media_library_nfo_parser import parse_nfo
from .media_library_nfo_paths import _find_nfo, _media_directory_reachable


def _candidate_rows(conn: sqlite3.Connection, *, full_audit: bool) -> list[sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT id, item_type, title, original_title, series_title, season, episode, year,
               path, nfo_status, nfo_path, nfo_mtime
        FROM media_items
        WHERE active=1 AND exists_flag=1
          AND item_type IN ('movie', 'episode', 'video', 'series', 'season')
        ORDER BY id
        """
    ).fetchall()
    if full_audit:
        return rows
    return [row for row in rows if _nfo_requires_scan(row)]


def _nfo_requires_scan(row: sqlite3.Row) -> bool:
    status = str(row["nfo_status"] or "unknown").casefold()
    if status in {"unknown", "missing", "unreachable", "invalid", "unreadable"} or not row["nfo_path"]:
        return True
    try:
        stored = Path(str(row["nfo_path"]))
        current_mtime = stored.stat().st_mtime if stored.is_file() else None
    except OSError:
        current_mtime = None
    return (
        current_mtime is None
        or row["nfo_mtime"] is None
        or abs(float(row["nfo_mtime"]) - current_mtime) > 0.001
    )


def _inspect_nfo_candidate(row: sqlite3.Row) -> dict[str, Any]:
    """Inspect filesystem/NFO content without holding a SQLite write transaction."""
    media_path = str(row["path"] or "")
    item_type = str(row["item_type"] or "")
    if not _media_directory_reachable(item_type, media_path):
        return {
            "status": "unreachable",
            "warning": f"Speicherpfad nicht erreichbar: {media_path}",
        }

    nfo_path = _find_nfo(item_type, media_path, row["nfo_path"])
    if nfo_path is None:
        return {"status": "missing"}
    try:
        return {
            "status": "present",
            "path": nfo_path,
            "mtime": nfo_path.stat().st_mtime,
            "parsed": parse_nfo(nfo_path),
        }
    except ET.ParseError as exc:
        return {"status": "invalid", "path": nfo_path, "error": str(exc)}
    except OSError as exc:
        return {
            "status": "unreadable",
            "path": nfo_path,
            "error": str(exc),
            "warning": f"NFO nicht lesbar: {nfo_path}: {exc}",
        }
