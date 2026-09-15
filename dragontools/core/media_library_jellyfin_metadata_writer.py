from __future__ import annotations

import sqlite3

from .media_library_jellyfin_metadata_types import JellyfinAuxMetadata


def apply_auxiliary_metadata(conn: sqlite3.Connection, media_id: int, source_id: str, aux: JellyfinAuxMetadata) -> None:
    conn.execute("DELETE FROM media_provider_ids WHERE media_id=?", (media_id,))
    for provider, provider_id in aux.providers_by_item.get(source_id, []):
        conn.execute("INSERT OR REPLACE INTO media_provider_ids(media_id, provider, provider_id, source) VALUES(?, ?, ?, 'jellyfin')", (media_id, provider, provider_id))

    conn.execute("DELETE FROM media_item_values WHERE media_id=?", (media_id,))
    for kind, value, sort_order in aux.values_by_item.get(source_id, []):
        normalized = value.strip().casefold()
        conn.execute("INSERT OR IGNORE INTO metadata_values(kind, value, normalized_value) VALUES(?, ?, ?)", (kind, value.strip(), normalized))
        row = conn.execute("SELECT id FROM metadata_values WHERE kind=? AND normalized_value=?", (kind, normalized)).fetchone()
        if row:
            conn.execute("INSERT OR REPLACE INTO media_item_values(media_id, value_id, sort_order) VALUES(?, ?, ?)", (media_id, int(row[0]), sort_order))

    conn.execute("DELETE FROM media_people WHERE media_id=?", (media_id,))
    for person in aux.people_by_item.get(source_id, []):
        conn.execute("INSERT OR IGNORE INTO people(source_id, name) VALUES(?, ?)", (person["source_id"], person["name"]))
        row = conn.execute("SELECT id FROM people WHERE source_id=?", (person["source_id"],)).fetchone()
        if row:
            conn.execute(
                "INSERT OR REPLACE INTO media_people(media_id, person_id, role_type, character_name, sort_order) VALUES(?, ?, ?, ?, ?)",
                (media_id, int(row[0]), person.get("role_type", ""), person.get("character_name", ""), int(person.get("sort_order", 0) or 0)),
            )


def apply_collection_metadata(conn: sqlite3.Connection, source_to_media_id: dict[str, int], aux: JellyfinAuxMetadata) -> None:
    for source_id, name in aux.collections.items():
        conn.execute("INSERT OR IGNORE INTO collections(source, source_id, name) VALUES('jellyfin', ?, ?)", (source_id, name))
        conn.execute("UPDATE collections SET name=? WHERE source='jellyfin' AND source_id=?", (name, source_id))
        row = conn.execute("SELECT id FROM collections WHERE source='jellyfin' AND source_id=?", (source_id,)).fetchone()
        if not row:
            continue
        collection_id = int(row[0])
        conn.execute("DELETE FROM collection_members WHERE collection_id=?", (collection_id,))
        for child_source_id, sort_order in aux.collection_members.get(source_id, []):
            media_id = source_to_media_id.get(child_source_id)
            if media_id is not None:
                conn.execute("INSERT OR REPLACE INTO collection_members(collection_id, media_id, sort_order) VALUES(?, ?, ?)", (collection_id, media_id, sort_order))


__all__ = ["apply_auxiliary_metadata", "apply_collection_metadata"]
