from __future__ import annotations

import json
import sqlite3
from typing import Any

from .media_library_db import _table_columns, _table_names
from .media_library_jellyfin_metadata_types import JellyfinAuxMetadata, actual, key


def split_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
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
    return [part.strip() for part in text.split(delimiter) if part.strip()] if delimiter else [text]


def kind_from_item_value_type(value: Any) -> str | None:
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
    item_col = actual(cols, "ItemId")
    provider_col = actual(cols, "ProviderId", "ProviderName", "Name")
    value_col = actual(cols, "ProviderValue", "Value", "ProviderIdValue")
    if not item_col or not provider_col or not value_col:
        return
    for row in conn.execute(f"SELECT * FROM {table}"):
        item_id = key(row[item_col])
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
    value_id_col = actual(value_cols, "ItemValueId", "Id")
    type_col = actual(value_cols, "Type", "ValueType")
    value_col = actual(value_cols, "Value", "Name")
    map_value_col = actual(map_cols, "ItemValueId", "ValueId")
    map_item_col = actual(map_cols, "ItemId")
    if not all((value_id_col, type_col, value_col, map_value_col, map_item_col)):
        return
    values: dict[str, tuple[str, str]] = {}
    for row in conn.execute("SELECT * FROM ItemValues"):
        kind = kind_from_item_value_type(row[type_col])
        value = str(row[value_col] or "").strip()
        value_id = key(row[value_id_col])
        if kind and value and value_id:
            values[value_id] = (kind, value)
    if not values:
        return
    for order, row in enumerate(conn.execute("SELECT * FROM ItemValuesMap")):
        item_id = key(row[map_item_col])
        payload = values.get(key(row[map_value_col]))
        if item_id and payload:
            kind, value = payload
            result.values_by_item.setdefault(item_id, []).append((kind, value, order))


def _load_people(conn: sqlite3.Connection, result: JellyfinAuxMetadata) -> None:
    tables = _table_names(conn)
    if "Peoples" not in tables or "PeopleBaseItemMap" not in tables:
        return
    people_cols = _table_columns(conn, "Peoples")
    map_cols = _table_columns(conn, "PeopleBaseItemMap")
    person_id_col = actual(people_cols, "Id", "PeopleId")
    name_col = actual(people_cols, "Name")
    person_type_col = actual(people_cols, "Type", "PersonType", "Kind")
    map_person_col = actual(map_cols, "PeopleId", "PersonId")
    item_col = actual(map_cols, "ItemId")
    role_col = actual(map_cols, "Role")
    sort_col = actual(map_cols, "SortOrder", "ListOrder")
    if not all((person_id_col, name_col, map_person_col, item_col)):
        return
    people: dict[str, tuple[str, str]] = {}
    for row in conn.execute("SELECT * FROM Peoples"):
        person_id = key(row[person_id_col])
        name = str(row[name_col] or "").strip()
        role_type = str(row[person_type_col] or "").strip() if person_type_col else ""
        if person_id and name:
            people[person_id] = (name, role_type)
    for idx, row in enumerate(conn.execute("SELECT * FROM PeopleBaseItemMap")):
        item_id = key(row[item_col])
        person_id = key(row[map_person_col])
        person = people.get(person_id)
        if not item_id or not person:
            continue
        name, role_type = person
        result.people_by_item.setdefault(item_id, []).append({
            "source_id": person_id,
            "name": name,
            "role_type": role_type,
            "character_name": str(row[role_col] or "").strip() if role_col else "",
            "sort_order": int(row[sort_col] or idx) if sort_col else idx,
        })


def _load_collections(conn: sqlite3.Connection, result: JellyfinAuxMetadata, item_table: str) -> None:
    item_cols = _table_columns(conn, item_table)
    id_col = actual(item_cols, "Id", "Guid", "ItemId", "InternalId")
    type_col = actual(item_cols, "Type")
    name_col = actual(item_cols, "Name", "OriginalTitle", "SortName")
    if id_col and type_col and name_col:
        for row in conn.execute(f"SELECT * FROM {item_table}"):
            raw_type = str(row[type_col] or "").split(",", 1)[0].rsplit(".", 1)[-1].casefold()
            if raw_type == "boxset":
                collection_id = key(row[id_col])
                name = str(row[name_col] or "").strip()
                if collection_id and name:
                    result.collections[collection_id] = name
    if "LinkedChildren" not in _table_names(conn):
        return
    cols = _table_columns(conn, "LinkedChildren")
    parent_col = actual(cols, "ParentId")
    child_col = actual(cols, "ChildId", "ItemId")
    sort_col = actual(cols, "SortOrder", "ListOrder")
    if not parent_col or not child_col:
        return
    for idx, row in enumerate(conn.execute("SELECT * FROM LinkedChildren")):
        parent_id = key(row[parent_col])
        child_id = key(row[child_col])
        if parent_id in result.collections and child_id:
            result.collection_members.setdefault(parent_id, []).append((child_id, int(row[sort_col] or idx) if sort_col else idx))


def _load_direct_item_values(rows: list[sqlite3.Row], item_columns: dict[str, str], result: JellyfinAuxMetadata) -> None:
    id_col = actual(item_columns, "Id", "Guid", "ItemId", "InternalId", "UserDataKey")
    if not id_col:
        return
    direct = {"genre": actual(item_columns, "Genres"), "studio": actual(item_columns, "Studios"), "tag": actual(item_columns, "Tags")}
    for row in rows:
        item_id = key(row[id_col])
        if not item_id:
            continue
        for kind, col in direct.items():
            if not col:
                continue
            existing = {(k, v.casefold()) for k, v, _ in result.values_by_item.get(item_id, [])}
            for value in split_values(row[col]):
                marker = (kind, value.casefold())
                if marker in existing:
                    continue
                order = len(result.values_by_item.get(item_id, []))
                result.values_by_item.setdefault(item_id, []).append((kind, value, order))
                existing.add(marker)


def load_jellyfin_auxiliary_metadata(conn: sqlite3.Connection, item_table: str, rows: list[sqlite3.Row], item_columns: dict[str, str]) -> JellyfinAuxMetadata:
    result = JellyfinAuxMetadata()
    _load_providers(conn, result)
    _load_item_values(conn, result)
    _load_direct_item_values(rows, item_columns, result)
    _load_people(conn, result)
    _load_collections(conn, result, item_table)
    return result


__all__ = ["load_jellyfin_auxiliary_metadata", "split_values", "kind_from_item_value_type"]
