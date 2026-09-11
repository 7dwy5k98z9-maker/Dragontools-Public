from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from .media_library_db import _table_columns, _table_names


@dataclass
class JellyfinAuxMetadata:
    providers_by_item: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    values_by_item: dict[str, list[tuple[str, str, int]]] = field(default_factory=dict)
    people_by_item: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    collections: dict[str, str] = field(default_factory=dict)
    collection_members: dict[str, list[tuple[str, int]]] = field(default_factory=dict)


def _key(value: Any) -> str:
    return str(value or "").strip().casefold()


def _actual(columns: dict[str, str], *names: str) -> str | None:
    for name in names:
        col = columns.get(name.casefold())
        if col:
            return col
    return None


def _split_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except Exception:
        parsed = None
    if isinstance(parsed, list):
        result: list[str] = []
        for item in parsed:
            if isinstance(item, dict):
                candidate = item.get("Name") or item.get("name") or item.get("Value") or item.get("value")
                if candidate:
                    result.append(str(candidate).strip())
            elif item is not None and str(item).strip():
                result.append(str(item).strip())
        return result
    if isinstance(parsed, dict):
        return [str(k).strip() for k, v in parsed.items() if v not in (None, "") and str(k).strip()]
    delimiter = "|" if "|" in text else ";" if ";" in text else None
    if delimiter:
        return [part.strip() for part in text.split(delimiter) if part.strip()]
    return [text]


def _kind_from_item_value_type(value: Any) -> str | None:
    text = str(value or "").strip().casefold()
    if text in {"2", "genre", "genres"} or "genre" in text:
        return "genre"
    if text in {"3", "studio", "studios"} or "studio" in text:
        return "studio"
    if text in {"4", "tag", "tags"} or text.endswith(".tags"):
        return "tag"
    return None


def _load_providers(conn: sqlite3.Connection, result: JellyfinAuxMetadata) -> None:
    tables = _table_names(conn)
    table = next((name for name in ("BaseItemProviders", "baseitemproviders") if name in tables), None)
    if not table:
        return
    cols = _table_columns(conn, table)
    item_col = _actual(cols, "ItemId")
    provider_col = _actual(cols, "ProviderId", "ProviderName", "Name")
    value_col = _actual(cols, "ProviderValue", "Value", "ProviderIdValue")
    if not item_col or not provider_col or not value_col:
        return
    for row in conn.execute(f"SELECT * FROM {table}"):
        item_id = _key(row[item_col])
        provider = str(row[provider_col] or "").strip().casefold()
        provider_id = str(row[value_col] or "").strip()
        if item_id and provider and provider_id:
            result.providers_by_item.setdefault(item_id, []).append((provider, provider_id))


def _load_item_values(conn: sqlite3.Connection, result: JellyfinAuxMetadata) -> None:
    tables = _table_names(conn)
    if "ItemValues" not in tables or "ItemValuesMap" not in tables:
        return
    value_cols = _table_columns(conn, "ItemValues")
    map_cols = _table_columns(conn, "ItemValuesMap")
    value_id_col = _actual(value_cols, "ItemValueId", "Id")
    type_col = _actual(value_cols, "Type", "ValueType")
    value_col = _actual(value_cols, "Value", "Name")
    map_value_col = _actual(map_cols, "ItemValueId", "ValueId")
    map_item_col = _actual(map_cols, "ItemId")
    if not all((value_id_col, type_col, value_col, map_value_col, map_item_col)):
        return
    values: dict[str, tuple[str, str]] = {}
    for row in conn.execute("SELECT * FROM ItemValues"):
        kind = _kind_from_item_value_type(row[type_col])
        value = str(row[value_col] or "").strip()
        value_id = _key(row[value_id_col])
        if kind and value and value_id:
            values[value_id] = (kind, value)
    if not values:
        return
    order = 0
    for row in conn.execute("SELECT * FROM ItemValuesMap"):
        item_id = _key(row[map_item_col])
        value_id = _key(row[map_value_col])
        payload = values.get(value_id)
        if item_id and payload:
            kind, value = payload
            result.values_by_item.setdefault(item_id, []).append((kind, value, order))
            order += 1


def _load_people(conn: sqlite3.Connection, result: JellyfinAuxMetadata) -> None:
    tables = _table_names(conn)
    if "Peoples" not in tables or "PeopleBaseItemMap" not in tables:
        return
    people_cols = _table_columns(conn, "Peoples")
    map_cols = _table_columns(conn, "PeopleBaseItemMap")
    person_id_col = _actual(people_cols, "Id", "PeopleId")
    name_col = _actual(people_cols, "Name")
    person_type_col = _actual(people_cols, "Type", "PersonType", "Kind")
    map_person_col = _actual(map_cols, "PeopleId", "PersonId")
    item_col = _actual(map_cols, "ItemId")
    role_col = _actual(map_cols, "Role")
    sort_col = _actual(map_cols, "SortOrder", "ListOrder")
    if not all((person_id_col, name_col, map_person_col, item_col)):
        return
    people: dict[str, tuple[str, str]] = {}
    for row in conn.execute("SELECT * FROM Peoples"):
        person_id = _key(row[person_id_col])
        name = str(row[name_col] or "").strip()
        role_type = str(row[person_type_col] or "").strip() if person_type_col else ""
        if person_id and name:
            people[person_id] = (name, role_type)
    for idx, row in enumerate(conn.execute("SELECT * FROM PeopleBaseItemMap")):
        item_id = _key(row[item_col])
        person_id = _key(row[map_person_col])
        person = people.get(person_id)
        if not item_id or not person:
            continue
        name, role_type = person
        result.people_by_item.setdefault(item_id, []).append(
            {
                "source_id": person_id,
                "name": name,
                "role_type": role_type,
                "character_name": str(row[role_col] or "").strip() if role_col else "",
                "sort_order": int(row[sort_col] or idx) if sort_col else idx,
            }
        )


def _load_collections(conn: sqlite3.Connection, result: JellyfinAuxMetadata, item_table: str) -> None:
    item_cols = _table_columns(conn, item_table)
    id_col = _actual(item_cols, "Id", "Guid", "ItemId", "InternalId")
    type_col = _actual(item_cols, "Type")
    name_col = _actual(item_cols, "Name", "OriginalTitle", "SortName")
    if id_col and type_col and name_col:
        for row in conn.execute(f"SELECT * FROM {item_table}"):
            raw_type = str(row[type_col] or "").split(",", 1)[0].rsplit(".", 1)[-1].casefold()
            if raw_type != "boxset":
                continue
            collection_id = _key(row[id_col])
            name = str(row[name_col] or "").strip()
            if collection_id and name:
                result.collections[collection_id] = name

    tables = _table_names(conn)
    if "LinkedChildren" not in tables:
        return
    cols = _table_columns(conn, "LinkedChildren")
    parent_col = _actual(cols, "ParentId")
    child_col = _actual(cols, "ChildId", "ItemId")
    sort_col = _actual(cols, "SortOrder", "ListOrder")
    if not parent_col or not child_col:
        return
    for idx, row in enumerate(conn.execute("SELECT * FROM LinkedChildren")):
        parent_id = _key(row[parent_col])
        child_id = _key(row[child_col])
        if parent_id not in result.collections or not child_id:
            continue
        sort_order = int(row[sort_col] or idx) if sort_col else idx
        result.collection_members.setdefault(parent_id, []).append((child_id, sort_order))


def _load_direct_item_values(rows: list[sqlite3.Row], item_columns: dict[str, str], result: JellyfinAuxMetadata) -> None:
    id_col = _actual(item_columns, "Id", "Guid", "ItemId", "InternalId", "UserDataKey")
    if not id_col:
        return
    direct = {
        "genre": _actual(item_columns, "Genres"),
        "studio": _actual(item_columns, "Studios"),
        "tag": _actual(item_columns, "Tags"),
    }
    for row in rows:
        item_id = _key(row[id_col])
        if not item_id:
            continue
        for kind, col in direct.items():
            if not col:
                continue
            existing = {(k, v.casefold()) for k, v, _ in result.values_by_item.get(item_id, [])}
            for value in _split_values(row[col]):
                key = (kind, value.casefold())
                if key in existing:
                    continue
                order = len(result.values_by_item.get(item_id, []))
                result.values_by_item.setdefault(item_id, []).append((kind, value, order))
                existing.add(key)


def load_jellyfin_auxiliary_metadata(
    conn: sqlite3.Connection,
    item_table: str,
    rows: list[sqlite3.Row],
    item_columns: dict[str, str],
) -> JellyfinAuxMetadata:
    result = JellyfinAuxMetadata()
    _load_providers(conn, result)
    _load_item_values(conn, result)
    _load_direct_item_values(rows, item_columns, result)
    _load_people(conn, result)
    _load_collections(conn, result, item_table)
    return result


def apply_auxiliary_metadata(
    conn: sqlite3.Connection,
    media_id: int,
    source_id: str,
    aux: JellyfinAuxMetadata,
) -> None:
    conn.execute("DELETE FROM media_provider_ids WHERE media_id=?", (media_id,))
    for provider, provider_id in aux.providers_by_item.get(source_id, []):
        conn.execute(
            "INSERT OR REPLACE INTO media_provider_ids(media_id, provider, provider_id, source) VALUES(?, ?, ?, 'jellyfin')",
            (media_id, provider, provider_id),
        )

    conn.execute("DELETE FROM media_item_values WHERE media_id=?", (media_id,))
    for kind, value, sort_order in aux.values_by_item.get(source_id, []):
        normalized = value.strip().casefold()
        conn.execute(
            "INSERT OR IGNORE INTO metadata_values(kind, value, normalized_value) VALUES(?, ?, ?)",
            (kind, value.strip(), normalized),
        )
        value_id_row = conn.execute(
            "SELECT id FROM metadata_values WHERE kind=? AND normalized_value=?",
            (kind, normalized),
        ).fetchone()
        if value_id_row:
            conn.execute(
                "INSERT OR REPLACE INTO media_item_values(media_id, value_id, sort_order) VALUES(?, ?, ?)",
                (media_id, int(value_id_row[0]), sort_order),
            )

    conn.execute("DELETE FROM media_people WHERE media_id=?", (media_id,))
    for person in aux.people_by_item.get(source_id, []):
        conn.execute(
            "INSERT OR IGNORE INTO people(source_id, name) VALUES(?, ?)",
            (person["source_id"], person["name"]),
        )
        person_row = conn.execute("SELECT id FROM people WHERE source_id=?", (person["source_id"],)).fetchone()
        if person_row:
            conn.execute(
                """
                INSERT OR REPLACE INTO media_people(
                    media_id, person_id, role_type, character_name, sort_order
                ) VALUES(?, ?, ?, ?, ?)
                """,
                (
                    media_id,
                    int(person_row[0]),
                    person.get("role_type", ""),
                    person.get("character_name", ""),
                    int(person.get("sort_order", 0) or 0),
                ),
            )


def apply_collection_metadata(conn: sqlite3.Connection, source_to_media_id: dict[str, int], aux: JellyfinAuxMetadata) -> None:
    for source_id, name in aux.collections.items():
        conn.execute(
            "INSERT OR IGNORE INTO collections(source, source_id, name) VALUES('jellyfin', ?, ?)",
            (source_id, name),
        )
        conn.execute(
            "UPDATE collections SET name=? WHERE source='jellyfin' AND source_id=?",
            (name, source_id),
        )
        collection_row = conn.execute(
            "SELECT id FROM collections WHERE source='jellyfin' AND source_id=?",
            (source_id,),
        ).fetchone()
        if not collection_row:
            continue
        collection_id = int(collection_row[0])
        conn.execute("DELETE FROM collection_members WHERE collection_id=?", (collection_id,))
        for child_source_id, sort_order in aux.collection_members.get(source_id, []):
            media_id = source_to_media_id.get(child_source_id)
            if media_id is None:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO collection_members(collection_id, media_id, sort_order) VALUES(?, ?, ?)",
                (collection_id, media_id, sort_order),
            )
