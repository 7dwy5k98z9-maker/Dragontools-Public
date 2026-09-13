from __future__ import annotations

import sqlite3


def _series_lookup_rows(
    conn: sqlite3.Connection,
    *,
    target_norm: str,
    series_name: str,
) -> list[sqlite3.Row]:
    """Return candidate rows for one series using the indexed key first.

    ``normalized_title`` is the fast primary path. A title-column fallback is
    retained only for legacy databases whose normalization value is stale.
    """
    plain_name = str(series_name or "").strip().casefold()
    if not target_norm and not plain_name:
        return []

    item_types = ("series", "folder", "season", "episode")
    placeholders = ",".join("?" for _ in item_types)
    order_sql = """
        ORDER BY
            CASE item_type
                WHEN 'series' THEN 0
                WHEN 'folder' THEN 1
                WHEN 'season' THEN 2
                WHEN 'episode' THEN 3
                ELSE 4
            END,
            coalesce(year, 999999),
            coalesce(series_title, title, filename, path)
        LIMIT 1000
    """

    # One indexed query covers every relevant item type. This prevents the
    # previous worst case of series/folder -> season -> episode scans.
    rows = conn.execute(
        f"""
        SELECT item_type, title, series_title, path, parent_path, year
        FROM media_items
        WHERE exists_flag=1
          AND active=1
          AND item_type IN ({placeholders})
          AND normalized_title=?
        {order_sql}
        """,
        (*item_types, target_norm),
    ).fetchall()
    if rows or not plain_name:
        return rows

    # Legacy fallback: at most one additional query, only after an indexed miss.
    return conn.execute(
        f"""
        SELECT item_type, title, series_title, path, parent_path, year
        FROM media_items
        WHERE exists_flag=1
          AND active=1
          AND item_type IN ({placeholders})
          AND (
              lower(trim(coalesce(series_title, '')))=?
              OR lower(trim(coalesce(title, '')))=?
          )
        {order_sql}
        """,
        (*item_types, plain_name, plain_name),
    ).fetchall()
