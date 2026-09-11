from __future__ import annotations

import sqlite3
import xml.etree.ElementTree as ET
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable

from .media_library_db import _connect, _create_schema, backup_database, initialize_database
from .media_library_types import AbortFn, LibraryLightScanResult, LogFn, ProgressFn, _now


def _int_text(value: str | None) -> int | None:
    try:
        return int(str(value or "").strip())
    except (TypeError, ValueError):
        return None


def _nfo_type_for_root(tag: str) -> str:
    tag = (tag or "").rsplit("}", 1)[-1].casefold()
    return {
        "movie": "movie",
        "episodedetails": "episode",
        "tvshow": "series",
        "season": "season",
    }.get(tag, tag or "unknown")


def _path_is_directory(item_type: str, path: Path) -> bool:
    """Best-effort path classification without relying on filename suffixes.

    Folder names such as ``Mr. Robot`` or ``Dr. Stone`` legitimately contain a
    dot.  ``Path.suffix`` therefore cannot distinguish files from directories.
    When the path is reachable, the filesystem is authoritative.  For an
    offline/unreachable path we fall back to the media type: series and season
    entries are directory-backed, movie/episode/video entries are file-backed.
    """
    try:
        if path.exists():
            return path.is_dir()
    except OSError:
        pass
    return str(item_type or "").casefold() in {"series", "season"}


def _media_directory(item_type: str, media_path: str) -> Path:
    path = Path(media_path)
    return path if _path_is_directory(item_type, path) else path.parent


def _candidate_nfo_paths(item_type: str, media_path: str) -> list[Path]:
    path = Path(media_path)
    is_directory = _path_is_directory(item_type, path)
    candidates: list[Path] = []
    if item_type == "series":
        candidates.append((path if is_directory else path.parent) / "tvshow.nfo")
    elif item_type == "season":
        candidates.append((path if is_directory else path.parent) / "season.nfo")
    elif item_type == "movie":
        base = path if is_directory else path.parent
        candidates.append(base / "movie.nfo")
        if is_directory:
            candidates.append(base / f"{base.name}.nfo")
        else:
            candidates.append(path.with_suffix(".nfo"))
    else:
        if is_directory:
            candidates.extend([path / "tvshow.nfo", path / "movie.nfo"])
        else:
            candidates.append(path.with_suffix(".nfo"))
    seen: set[str] = set()
    result: list[Path] = []
    for candidate in candidates:
        key = str(candidate).casefold()
        if key not in seen:
            seen.add(key)
            result.append(candidate)
    return result


def _find_nfo(item_type: str, media_path: str, stored_path: str | None = None) -> Path | None:
    candidates: list[Path] = []
    if stored_path:
        candidates.append(Path(stored_path))
    candidates.extend(_candidate_nfo_paths(item_type, media_path))
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def _media_directory_reachable(item_type: str, media_path: str) -> bool:
    """Return whether the directory containing the known media item is reachable.

    A missing NFO can only be asserted when its containing media directory can
    actually be inspected.  The directory is derived from the known media type
    rather than ``Path.suffix`` so dotted folder names (for example
    ``Mr. Robot``) remain folders even while a NAS/share is offline.
    """
    directory = _media_directory(item_type, media_path)
    try:
        return directory.is_dir()
    except OSError:
        return False


def _child_text(root: ET.Element, *tags: str) -> str | None:
    wanted = {tag.casefold() for tag in tags}
    for child in root:
        local = child.tag.rsplit("}", 1)[-1].casefold()
        if local in wanted:
            text = (child.text or "").strip()
            if text:
                return text
    return None


def _provider_ids(root: ET.Element) -> dict[str, str]:
    result: dict[str, str] = {}
    for child in root.iter():
        local = child.tag.rsplit("}", 1)[-1].casefold()
        text = (child.text or "").strip()
        if not text:
            continue
        if local == "uniqueid":
            provider = str(child.attrib.get("type") or "").strip().casefold()
            if provider:
                result[provider] = text
            continue
        if local in {"tmdbid", "tvdbid", "imdbid"}:
            result[local[:-2]] = text
            continue
        if local.endswith("id") and local not in {"id", "uniqueid"}:
            provider = local[:-2].strip()
            if provider and provider not in {"musicbrainzalbum", "musicbrainzartist", "audiodbartist", "audiodbalbum"}:
                result.setdefault(provider, text)
    return result


def parse_nfo(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    root = ET.parse(source).getroot()
    return {
        "nfo_type": _nfo_type_for_root(root.tag),
        "title": _child_text(root, "title"),
        "original_title": _child_text(root, "originaltitle", "original_title"),
        "series_title": _child_text(root, "showtitle", "seriesname"),
        "season": _int_text(_child_text(root, "season")),
        "episode": _int_text(_child_text(root, "episode")),
        "year": _int_text(_child_text(root, "year")),
        "runtime_minutes": _int_text(_child_text(root, "runtime")),
        "provider_ids": _provider_ids(root),
    }


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _replace_nfo_issues(
    conn: sqlite3.Connection,
    media_id: int,
    db_row: sqlite3.Row,
    parsed: dict[str, Any],
) -> int:
    checked_at = _now()
    conn.execute("DELETE FROM nfo_issues WHERE media_id=?", (media_id,))
    issues: list[tuple[str, str, Any, Any, str]] = []

    expected_type = {"movie": "movie", "episode": "episode", "series": "series", "season": "season"}.get(
        str(db_row["item_type"] or "").casefold()
    )
    if expected_type and parsed.get("nfo_type") not in {expected_type, "unknown"}:
        issues.append(("ERROR", "nfo_type", expected_type, parsed.get("nfo_type"), "NFO-Typ passt nicht zum Medieneintrag."))

    for field, severity in (("season", "ERROR"), ("episode", "ERROR"), ("year", "WARNING")):
        db_value = db_row[field]
        nfo_value = parsed.get(field)
        if db_value is not None and nfo_value is not None and int(db_value) != int(nfo_value):
            issues.append((severity, field, db_value, nfo_value, f"{field} stimmt zwischen DB und NFO nicht überein."))

    for field in ("title", "original_title"):
        db_value = db_row[field]
        nfo_value = parsed.get(field)
        if db_value and nfo_value and _normalize_text(db_value) != _normalize_text(nfo_value):
            issues.append(("INFO", field, db_value, nfo_value, f"{field} unterscheidet sich zwischen DB und NFO."))

    db_provider_rows = conn.execute(
        "SELECT provider, provider_id FROM media_provider_ids WHERE media_id=?",
        (media_id,),
    ).fetchall()
    db_providers = {str(row["provider"]).casefold(): str(row["provider_id"]) for row in db_provider_rows}
    nfo_providers = {str(k).casefold(): str(v) for k, v in (parsed.get("provider_ids") or {}).items()}
    for provider in sorted(set(db_providers) | set(nfo_providers)):
        db_value = db_providers.get(provider)
        nfo_value = nfo_providers.get(provider)
        if db_value and nfo_value and db_value != nfo_value:
            issues.append(("ERROR", f"provider:{provider}", db_value, nfo_value, f"{provider.upper()}-ID stimmt zwischen DB und NFO nicht überein."))
        elif db_value and not nfo_value:
            issues.append(("WARNING", f"provider:{provider}", db_value, None, f"{provider.upper()}-ID fehlt in der NFO."))
        elif nfo_value and not db_value:
            issues.append(("INFO", f"provider:{provider}", None, nfo_value, f"{provider.upper()}-ID ist nur in der NFO vorhanden."))

    for severity, field, db_value, nfo_value, message in issues:
        conn.execute(
            """
            INSERT INTO nfo_issues(media_id, severity, field, db_value, nfo_value, message, checked_at)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (
                media_id,
                severity,
                field,
                None if db_value is None else str(db_value),
                None if nfo_value is None else str(nfo_value),
                message,
                checked_at,
            ),
        )
    return len(issues)


def _store_parsed_nfo(conn: sqlite3.Connection, media_id: int, parsed: dict[str, Any]) -> int:
    conn.execute(
        """
        INSERT OR REPLACE INTO nfo_metadata(
            media_id, title, original_title, series_title, season, episode, year,
            runtime_minutes, parse_status, parse_error, parsed_at
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, 'ok', NULL, ?)
        """,
        (
            media_id,
            parsed.get("title"),
            parsed.get("original_title"),
            parsed.get("series_title"),
            parsed.get("season"),
            parsed.get("episode"),
            parsed.get("year"),
            parsed.get("runtime_minutes"),
            _now(),
        ),
    )
    conn.execute("DELETE FROM nfo_provider_ids WHERE media_id=?", (media_id,))
    for provider, provider_id in (parsed.get("provider_ids") or {}).items():
        conn.execute(
            "INSERT OR REPLACE INTO nfo_provider_ids(media_id, provider, provider_id) VALUES(?, ?, ?)",
            (media_id, str(provider).casefold(), str(provider_id)),
        )
    return 1


def _mark_parse_error(conn: sqlite3.Connection, media_id: int, status: str, error: str) -> None:
    conn.execute("DELETE FROM nfo_provider_ids WHERE media_id=?", (media_id,))
    conn.execute("DELETE FROM nfo_issues WHERE media_id=?", (media_id,))
    conn.execute(
        """
        INSERT OR REPLACE INTO nfo_metadata(
            media_id, parse_status, parse_error, parsed_at
        ) VALUES(?, ?, ?, ?)
        """,
        (media_id, status, error, _now()),
    )


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
    result: list[sqlite3.Row] = []
    for row in rows:
        status = str(row["nfo_status"] or "unknown").casefold()
        if status in {"unknown", "missing", "unreachable", "invalid", "unreadable"} or not row["nfo_path"]:
            result.append(row)
            continue
        try:
            stored = Path(str(row["nfo_path"]))
            current_mtime = stored.stat().st_mtime if stored.is_file() else None
        except OSError:
            current_mtime = None
        if current_mtime is None or row["nfo_mtime"] is None or abs(float(row["nfo_mtime"]) - current_mtime) > 0.001:
            result.append(row)
    return result


def scan_nfo_inventory(
    db_path: str | Path,
    *,
    full_audit: bool = False,
    backup: bool = True,
    logger: LogFn = None,
    progress: ProgressFn = None,
    should_abort: AbortFn = None,
) -> LibraryLightScanResult:
    db = initialize_database(db_path)
    with closing(_connect(db)) as conn:
        _create_schema(conn)
        candidates = _candidate_rows(conn, full_audit=full_audit)

    if candidates and backup:
        backup_database(db, "pre_nfo_lightscan")

    present = missing = unreachable = invalid = issues = scanned = 0
    warnings: list[str] = []
    aborted = False
    with closing(_connect(db)) as conn:
        with conn:
            _create_schema(conn)
            total = len(candidates)
            for index, row in enumerate(candidates, start=1):
                if should_abort and should_abort():
                    aborted = True
                    break
                media_id = int(row["id"])
                media_path = str(row["path"] or "")
                if progress:
                    progress(index, total, media_path)
                if not _media_directory_reachable(str(row["item_type"] or ""), media_path):
                    scanned += 1
                    unreachable += 1
                    now = _now()
                    conn.execute(
                        """
                        UPDATE media_items
                           SET nfo_status='unreachable', nfo_scanned_at=?, updated_at=?
                         WHERE id=?
                        """,
                        (now, now, media_id),
                    )
                    warnings.append(f"Speicherpfad nicht erreichbar: {media_path}")
                    continue

                nfo_path = _find_nfo(str(row["item_type"] or ""), media_path, row["nfo_path"])
                scanned += 1
                if nfo_path is None:
                    missing += 1
                    conn.execute(
                        """
                        UPDATE media_items
                           SET nfo_status='missing', nfo_path=NULL, nfo_type=NULL,
                               nfo_mtime=NULL, nfo_scanned_at=?, updated_at=?
                         WHERE id=?
                        """,
                        (_now(), _now(), media_id),
                    )
                    conn.execute("DELETE FROM nfo_metadata WHERE media_id=?", (media_id,))
                    conn.execute("DELETE FROM nfo_provider_ids WHERE media_id=?", (media_id,))
                    conn.execute("DELETE FROM nfo_issues WHERE media_id=?", (media_id,))
                    continue

                try:
                    mtime = nfo_path.stat().st_mtime
                    parsed = parse_nfo(nfo_path)
                    _store_parsed_nfo(conn, media_id, parsed)
                    issue_count = _replace_nfo_issues(conn, media_id, row, parsed)
                    issues += issue_count
                    present += 1
                    conn.execute(
                        """
                        UPDATE media_items
                           SET nfo_status='present', nfo_path=?, nfo_type=?, nfo_mtime=?,
                               nfo_scanned_at=?, updated_at=?
                         WHERE id=?
                        """,
                        (str(nfo_path), parsed.get("nfo_type"), mtime, _now(), _now(), media_id),
                    )
                except ET.ParseError as exc:
                    invalid += 1
                    _mark_parse_error(conn, media_id, "invalid", str(exc))
                    conn.execute(
                        "UPDATE media_items SET nfo_status='invalid', nfo_path=?, nfo_scanned_at=?, updated_at=? WHERE id=?",
                        (str(nfo_path), _now(), _now(), media_id),
                    )
                except OSError as exc:
                    invalid += 1
                    _mark_parse_error(conn, media_id, "unreadable", str(exc))
                    conn.execute(
                        "UPDATE media_items SET nfo_status='unreadable', nfo_path=?, nfo_scanned_at=?, updated_at=? WHERE id=?",
                        (str(nfo_path), _now(), _now(), media_id),
                    )
                    warnings.append(f"NFO nicht lesbar: {nfo_path}: {exc}")
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('updated_at', ?)", (_now(),))

    if logger:
        logger(
            f"NFO-Lightscan: {scanned}/{len(candidates)} geprüft, {present} vorhanden, "
            f"{missing} fehlend, {unreachable} nicht erreichbar, {invalid} fehlerhaft, {issues} Abweichungen."
        )
    return LibraryLightScanResult(
        db_path=db,
        candidates=len(candidates),
        scanned_items=scanned,
        nfo_present=present,
        nfo_missing=missing,
        nfo_unreachable=unreachable,
        nfo_invalid=invalid,
        issues=issues,
        aborted=aborted,
        warnings=tuple(warnings),
    )
