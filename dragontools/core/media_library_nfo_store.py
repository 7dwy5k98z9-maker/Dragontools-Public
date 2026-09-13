from __future__ import annotations

import sqlite3
from typing import Any

from .media_library_types import _now


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

    expected_type = {
        "movie": "movie",
        "episode": "episode",
        "series": "series",
        "season": "season",
    }.get(str(db_row["item_type"] or "").casefold())
    if expected_type and parsed.get("nfo_type") not in {expected_type, "unknown"}:
        issues.append((
            "ERROR",
            "nfo_type",
            expected_type,
            parsed.get("nfo_type"),
            "NFO-Typ passt nicht zum Medieneintrag.",
        ))

    for field, severity in (("season", "ERROR"), ("episode", "ERROR"), ("year", "WARNING")):
        db_value = db_row[field]
        nfo_value = parsed.get(field)
        if db_value is not None and nfo_value is not None and int(db_value) != int(nfo_value):
            issues.append((
                severity,
                field,
                db_value,
                nfo_value,
                f"{field} stimmt zwischen DB und NFO nicht überein.",
            ))

    for field in ("title", "original_title"):
        db_value = db_row[field]
        nfo_value = parsed.get(field)
        if db_value and nfo_value and _normalize_text(db_value) != _normalize_text(nfo_value):
            issues.append((
                "INFO",
                field,
                db_value,
                nfo_value,
                f"{field} unterscheidet sich zwischen DB und NFO.",
            ))

    db_provider_rows = conn.execute(
        "SELECT provider, provider_id FROM media_provider_ids WHERE media_id=?",
        (media_id,),
    ).fetchall()
    db_providers = {
        str(row["provider"]).casefold(): str(row["provider_id"])
        for row in db_provider_rows
    }
    nfo_providers = {
        str(key).casefold(): str(value)
        for key, value in (parsed.get("provider_ids") or {}).items()
    }
    for provider in sorted(set(db_providers) | set(nfo_providers)):
        db_value = db_providers.get(provider)
        nfo_value = nfo_providers.get(provider)
        if db_value and nfo_value and db_value != nfo_value:
            issues.append((
                "ERROR",
                f"provider:{provider}",
                db_value,
                nfo_value,
                f"{provider.upper()}-ID stimmt zwischen DB und NFO nicht überein.",
            ))
        elif db_value and not nfo_value:
            issues.append((
                "WARNING",
                f"provider:{provider}",
                db_value,
                None,
                f"{provider.upper()}-ID fehlt in der NFO.",
            ))
        elif nfo_value and not db_value:
            issues.append((
                "INFO",
                f"provider:{provider}",
                None,
                nfo_value,
                f"{provider.upper()}-ID ist nur in der NFO vorhanden.",
            ))

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


def _store_parsed_nfo(conn: sqlite3.Connection, media_id: int, parsed: dict[str, Any]) -> None:
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


def _mark_parse_error(conn: sqlite3.Connection, media_id: int, status: str, error: str) -> None:
    conn.execute("DELETE FROM nfo_provider_ids WHERE media_id=?", (media_id,))
    conn.execute("DELETE FROM nfo_issues WHERE media_id=?", (media_id,))
    conn.execute(
        """
        INSERT OR REPLACE INTO nfo_metadata(media_id, parse_status, parse_error, parsed_at)
        VALUES(?, ?, ?, ?)
        """,
        (media_id, status, error, _now()),
    )


def _apply_nfo_scan_batch(
    conn: sqlite3.Connection,
    batch: list[tuple[sqlite3.Row, dict[str, Any]]],
) -> int:
    if not batch:
        return 0
    issue_count = 0
    with conn:
        for row, result in batch:
            issue_count += _apply_nfo_scan_result(conn, row, result)
        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('updated_at', ?)", (_now(),))
    return issue_count


def _apply_nfo_scan_result(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    result: dict[str, Any],
) -> int:
    media_id = int(row["id"])
    status = str(result.get("status") or "invalid")
    now = _now()
    if status == "unreachable":
        conn.execute(
            "UPDATE media_items SET nfo_status='unreachable', nfo_scanned_at=?, updated_at=? WHERE id=?",
            (now, now, media_id),
        )
        return 0
    if status == "missing":
        conn.execute(
            """
            UPDATE media_items
               SET nfo_status='missing', nfo_path=NULL, nfo_type=NULL,
                   nfo_mtime=NULL, nfo_scanned_at=?, updated_at=?
             WHERE id=?
            """,
            (now, now, media_id),
        )
        conn.execute("DELETE FROM nfo_metadata WHERE media_id=?", (media_id,))
        conn.execute("DELETE FROM nfo_provider_ids WHERE media_id=?", (media_id,))
        conn.execute("DELETE FROM nfo_issues WHERE media_id=?", (media_id,))
        return 0

    nfo_path = result.get("path")
    if status == "present":
        parsed = dict(result.get("parsed") or {})
        _store_parsed_nfo(conn, media_id, parsed)
        issue_count = _replace_nfo_issues(conn, media_id, row, parsed)
        conn.execute(
            """
            UPDATE media_items
               SET nfo_status='present', nfo_path=?, nfo_type=?, nfo_mtime=?,
                   nfo_scanned_at=?, updated_at=?
             WHERE id=?
            """,
            (
                str(nfo_path),
                parsed.get("nfo_type"),
                result.get("mtime"),
                now,
                now,
                media_id,
            ),
        )
        return issue_count

    _mark_parse_error(conn, media_id, status, str(result.get("error") or ""))
    conn.execute(
        "UPDATE media_items SET nfo_status=?, nfo_path=?, nfo_scanned_at=?, updated_at=? WHERE id=?",
        (status, str(nfo_path or ""), now, now, media_id),
    )
    return 0
