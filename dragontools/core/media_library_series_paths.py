from __future__ import annotations

import sqlite3
import re
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable

from .media_library_db import _connect, initialize_database
from .media_library_types import PathMapping, default_media_library_db_path, describe_series_path_resolution
from .media_library_utils import _normalize_title
from .paths import join_user_path, normalize_user_path, path_compare_key, path_is_same_or_child, user_path_name, user_path_parent
from .media_library_path_mappings import (
    _area_from_root, _area_key, _area_label, _join_mapped_path, _matching_current_mappings,
    _mapping_candidates_from_search_bases, _normalize_slashes, _prefix_rest, _unique_mappings,
    apply_path_mappings, get_path_mappings, load_path_mappings,
)

def _year_suffix_from_text(value: str | None) -> int | None:
    match = re.search(r"\((19\d{2}|20\d{2})\)\s*$", str(value or "").strip())
    return int(match.group(1)) if match else None

def _series_root_candidates_for_current_paths(
    root: str,
    *,
    current_mappings: Iterable[PathMapping] = (),
    stored_mappings: Iterable[PathMapping] = (),
    search_bases: Iterable[tuple[str, str]] = (),
) -> list[tuple[str, str]]:
    """Erzeugt plausible aktuelle Zielpfade fuer einen DB-Serienordner.

    Die Mediathek kann alte lokale Pfade enthalten, waehrend die aktuellen
    Speicherpfade inzwischen anders eingestellt sind. Fuer den Preflight ist
    wichtig, dass solche Treffer nicht blind uebernommen werden, sondern auf
    den aktuellen Move-Basisordner umgebogen oder als unbrauchbar gemeldet
    werden.
    """
    current = _unique_mappings(current_mappings)
    stored = _unique_mappings(stored_mappings)
    bases = [(str(base or "").strip(), str(label or "").strip()) for base, label in search_bases or []]
    root_area = _area_from_root(root, [*stored, *current])

    result: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(candidate: str, note: str = "") -> None:
        if not candidate:
            return
        try:
            normalized = normalize_user_path(candidate)
            key = path_compare_key(normalized)
        except Exception:
            normalized = str(candidate)
            key = _normalize_slashes(normalized).casefold()
        if not key or key in seen:
            return
        seen.add(key)
        result.append((normalized, note))

    add(root)
    if current:
        mapped = apply_path_mappings(root, current)
        note = "external_to_current" if path_compare_key(mapped) != path_compare_key(root) else ""
        add(mapped, note)
    if stored:
        mapped = apply_path_mappings(root, stored)
        add(mapped, "stored_mapping" if path_compare_key(mapped) != path_compare_key(root) else "")

    for stored_mapping in stored:
        matching_current = _matching_current_mappings(stored_mapping, current)
        if not matching_current:
            continue
        for prefix in (stored_mapping.local_prefix, stored_mapping.external_prefix):
            rest = _prefix_rest(root, prefix)
            if rest is None:
                continue
            for current_mapping in matching_current:
                add(_join_mapped_path(current_mapping.local_prefix, rest), "rebased_from_persisted_mapping")

    # Falls alte Mapping-Historie nicht mehr vorhanden ist, kann der
    # Serienordnername trotzdem auf die aktuelle Basis gemappt werden.
    # Das wird nur mit require_existing akzeptiert, wenn der Ordner wirklich existiert.
    root_name = user_path_name(root)
    if root_name:
        for base, label in bases:
            if base:
                if root_area and _area_key(label) != root_area:
                    continue
                add(join_user_path(base, root_name), "rebased_from_series_folder_name")

    return result

def _series_lookup_rows(
    conn: sqlite3.Connection,
    *,
    target_norm: str,
    series_name: str,
) -> list[sqlite3.Row]:
    """Liefert nur DB-Zeilen, die als Serienwurzel wirklich infrage kommen.

    Der Preflight ruft diese Suche pro Seriengruppe auf. Bei großen Mediatheken
    darf hier nicht der gesamte Bestand in Python normalisiert werden; SQLite
    soll zuerst anhand des gespeicherten Normalisierungsschlüssels eingrenzen.
    """
    plain_name = str(series_name or "").strip().casefold()
    if not target_norm and not plain_name:
        return []

    select_sql = """
        SELECT item_type, title, series_title, path, parent_path, year
        FROM media_items
        WHERE exists_flag=1
          AND active=1
          AND item_type IN ({placeholders})
          AND (
              normalized_title=?
              OR lower(trim(coalesce(series_title, '')))=?
              OR lower(trim(coalesce(title, '')))=?
          )
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
    for item_types in (("series", "folder"), ("season",), ("episode",)):
        placeholders = ",".join("?" for _ in item_types)
        rows = conn.execute(
            select_sql.format(placeholders=placeholders),
            (*item_types, target_norm, plain_name, plain_name),
        ).fetchall()
        if rows:
            return rows
    return []

def find_series_root(
    db_path: str | Path,
    series_name: str,
    search_bases: Iterable[tuple[str, str]] | Iterable[str] = (),
    *,
    mappings: Iterable[PathMapping] = (),
    stored_mappings: Iterable[PathMapping] = (),
    require_existing: bool = False,
    include_unusable: bool = False,
    year: int | None = None,
) -> dict[str, str] | None:
    db = Path(db_path)
    if not db.exists() or not series_name:
        return None
    initialize_database(db)
    target_norm = _normalize_title(series_name)
    if not target_norm:
        return None
    target_year = _year_suffix_from_text(series_name) or (int(year) if year else None)

    bases: list[tuple[str, str]] = []
    for entry in search_bases or []:
        if isinstance(entry, tuple):
            bases.append((str(entry[0]), str(entry[1] or "")))
        else:
            bases.append((str(entry), ""))

    with closing(_connect(db)) as conn:
        rows = _series_lookup_rows(conn, target_norm=target_norm, series_name=series_name)

    search_base_mappings = _mapping_candidates_from_search_bases(bases)
    current_mappings = _unique_mappings([*(mappings or []), *search_base_mappings])
    stored_mappings_list = _unique_mappings(stored_mappings or [])
    rejected: dict[str, str] = {}

    def remember_rejected(root: str, mapped_root: str, reason: str, matched_base: tuple[str, str] | None) -> None:
        nonlocal rejected
        if rejected and not matched_base:
            return
        area = _area_from_root(root, [*stored_mappings_list, *current_mappings])
        base_type = matched_base[1] if matched_base else _area_label(area)
        prefix = "Mediathek-Treffer ist aktuell nicht erreichbar"
        if base_type:
            prefix += f" (Bereich {base_type})"
        message = f"{prefix}: {mapped_root}"
        db_path = normalize_user_path(root)
        if db_path and path_compare_key(db_path) != path_compare_key(mapped_root):
            message += f" | DB-Pfad: {db_path}"
        if reason:
            message += f" | Grund: {reason}"
        rejected = {
            "series_dir": "",
            "base": matched_base[0] if matched_base else "",
            "base_type": base_type,
            "source": "database",
            "unusable_reason": message,
            "suggested_series_name": user_path_name(root) or series_name,
            "database_path": db_path,
        }

    for row in rows:
        name = str(row["series_title"] or row["title"] or "")
        if _normalize_title(name) != target_norm:
            continue
        root = _series_root_from_db_row(row)
        if not root:
            continue
        row_year = row["year"] if "year" in row.keys() else None
        try:
            row_year = int(row_year) if row_year else None
        except (TypeError, ValueError):
            row_year = None
        candidate_year = _year_suffix_from_text(user_path_name(root)) or row_year
        if target_year and candidate_year and candidate_year != target_year:
            continue
        for mapped_root, note in _series_root_candidates_for_current_paths(
            root,
            current_mappings=current_mappings,
            stored_mappings=stored_mappings_list,
            search_bases=bases,
        ):
            matched_base = _match_base(mapped_root, bases)
            if bases and not matched_base:
                remember_rejected(
                    root,
                    mapped_root,
                    "liegt nicht unter den aktuell eingestellten Speicherpfaden",
                    matched_base,
                )
                continue
            if require_existing and not Path(mapped_root).is_dir():
                remember_rejected(root, mapped_root, "Ordner existiert nicht oder ist nicht erreichbar", matched_base)
                continue
            result = {
                "series_dir": mapped_root,
                "base": matched_base[0] if matched_base else user_path_parent(mapped_root),
                "base_type": matched_base[1] if matched_base else "",
                "source": "database",
            }
            result["mapping_notice"] = describe_series_path_resolution(
                note,
                result["base_type"],
            )
            if note:
                result["mapping_note"] = note
                result["database_path"] = normalize_user_path(root)
            root_name = user_path_name(root)
            if root_name and _normalize_title(root_name) != _normalize_title(series_name):
                result["suggested_series_name"] = root_name
            return result
    if include_unusable and rejected:
        return rejected
    return None


def _series_root_from_db_row(row: sqlite3.Row) -> str:
    path = str(row["path"] or row["parent_path"] or "")
    item_type = str(row["item_type"] or "").casefold()
    if item_type == "series":
        return path
    if item_type == "season":
        return user_path_parent(path)
    if item_type == "episode":
        parent = user_path_parent(path)
        if user_path_name(parent).casefold().startswith(("staffel", "season", "saison", "special")):
            return user_path_parent(parent)
        return parent
    return path


def _match_base(path: str, bases: list[tuple[str, str]]) -> tuple[str, str] | None:
    for base, base_type in bases:
        if path_is_same_or_child(path, base):
            return base, base_type
    return None


def find_series_dir_from_settings(
    settings: Any,
    series_name: str,
    search_bases: Iterable[tuple[str, str]],
    *,
    year: int | None = None,
) -> dict[str, str] | None:
    from .settings import (
        SET_KEY_MEDIA_LIBRARY_DB_PATH,
        SET_KEY_MEDIA_LIBRARY_ENABLED,
        SET_KEY_MEDIA_LIBRARY_PATH_MAPPINGS,
        SET_KEY_MEDIA_LIBRARY_PREFLIGHT_ENABLED,
    )

    if not settings.value(SET_KEY_MEDIA_LIBRARY_ENABLED, False, type=bool):
        return None
    if not settings.value(SET_KEY_MEDIA_LIBRARY_PREFLIGHT_ENABLED, True, type=bool):
        return None
    db_path = settings.value(SET_KEY_MEDIA_LIBRARY_DB_PATH, str(default_media_library_db_path()), type=str)
    if not db_path:
        return None
    configured_mappings = load_path_mappings(settings.value(SET_KEY_MEDIA_LIBRARY_PATH_MAPPINGS, "", type=str))
    stored_mappings: list[PathMapping] = []
    try:
        stored_mappings = get_path_mappings(db_path)
    except Exception:
        stored_mappings = []
    mappings = configured_mappings or stored_mappings
    if not mappings:
        try:
            mappings = get_path_mappings(db_path)
        except Exception:
            mappings = []
    return find_series_root(
        db_path,
        series_name,
        search_bases,
        mappings=mappings,
        stored_mappings=stored_mappings,
        require_existing=True,
        include_unusable=True,
        year=year,
    )
