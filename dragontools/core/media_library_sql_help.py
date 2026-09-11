from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from .media_library_db import _connect, initialize_database


_TABLE_DESCRIPTIONS = {
    "media_items": "Ein Medieneintrag pro Film, Serie, Staffel, Episode oder Video.",
    "media_streams": "Video-, Audio- und Untertitelspuren eines Medieneintrags.",
    "media_provider_ids": "TMDB/TVDB/IMDb-IDs aus der importierten Mediathek.",
    "metadata_values": "Normalisierte Genres, Tags und Studios.",
    "media_item_values": "Verknüpft Medien mit Genres, Tags und Studios.",
    "people": "Nur Personen-ID und Name; keine Biografien oder Bilder.",
    "media_people": "Verknüpft Personen mit Medien inklusive Rolle/Charakter.",
    "collections": "Filmreihen/Boxsets/Collections.",
    "collection_members": "Mitglieder einer Collection.",
    "nfo_metadata": "Aus der vorhandenen NFO gelesene Kontrollwerte; keine Quelle für NFO-Erstellung.",
    "nfo_provider_ids": "Provider-IDs, die tatsächlich in der NFO stehen.",
    "nfo_issues": "Gefundene Abweichungen zwischen Mediathek-DB und NFO.",
    "path_mappings": "Übersetzung Jellyfin-Pfad → lokaler/NAS-Pfad.",
    "meta": "Schema-Version und interne Zeitstempel.",
}

_COLUMN_HINTS = {
    ("media_items", "item_type"): "Typische Werte: movie, series, season, episode, video.",
    ("media_items", "nfo_status"): "Werte: unknown, present, missing, unreachable, invalid, unreadable.",
    ("media_items", "active"): "1 = aktiv, 0 = ersetzt/inaktiv.",
    ("media_items", "exists_flag"): "1 = vorhanden, 0 = als nicht vorhanden markiert.",
    ("media_provider_ids", "provider"): "Typische Werte: tmdb, tvdb, imdb.",
    ("metadata_values", "kind"): "Werte: genre, tag, studio.",
    ("nfo_issues", "severity"): "Werte: INFO, WARNING, ERROR.",
    ("nfo_issues", "field"): "z. B. season, episode, year, title oder provider:tmdb.",
}

_SQL_REFERENCE = """## SQL-Schnellhilfe

Lesen / Filtern:
- SELECT ... FROM ...
- WHERE Bedingung
- AND / OR / NOT
- LIKE '%text%' für Teilstrings
- IN ('a', 'b') für mehrere Werte
- BETWEEN x AND y für Bereiche
- IS NULL / IS NOT NULL
- ORDER BY spalte ASC|DESC
- GROUP BY spalte
- HAVING ... für Filter nach GROUP BY
- DISTINCT zum Entfernen doppelter Werte
- LIMIT 100 zum Begrenzen
- JOIN ... ON ... zum Verknüpfen von Tabellen
- EXISTS (...) für Existenzprüfungen
- WITH name AS (...) für Common Table Expressions (CTE)
- Vergleichsoperatoren: =, <>, <, <=, >, >=
- COUNT(*), MIN(), MAX(), AVG(), SUM()

Schema direkt per SQL ansehen:
- PRAGMA table_info(media_items);
- PRAGMA index_list(media_items);
- SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;

Änderungen (mit automatischem DB-Backup):
- UPDATE tabelle SET spalte=wert WHERE ...
- DELETE FROM tabelle WHERE ...
- INSERT INTO tabelle(...) VALUES(...)

Hinweis: DragonTools behandelt nur reine SELECT-Abfragen als sicher lesend. WITH/PRAGMA und alle Änderungsbefehle lösen vorsichtshalber ein Backup aus.
"""

_EXAMPLES = """## Praktische Beispiele

### Episoden ohne NFO
```sql
SELECT series_title, season, episode, title, path
FROM media_items
WHERE active=1 AND item_type='episode' AND nfo_status='missing'
ORDER BY series_title, season, episode;
```

### NFO-Pfade aktuell nicht erreichbar
```sql
SELECT title, series_title, season, episode, path, nfo_path
FROM media_items
WHERE active=1 AND nfo_status='unreachable'
ORDER BY path;
```

### NFO mit kritischen Abweichungen
```sql
SELECT mi.title, mi.path, ni.field, ni.db_value, ni.nfo_value, ni.message
FROM nfo_issues ni
JOIN media_items mi ON mi.id=ni.media_id
WHERE ni.severity='ERROR'
ORDER BY mi.path, ni.field;
```

### Provider-ID DB gegen NFO vergleichen
```sql
SELECT mi.title,
       db.provider,
       db.provider_id AS db_id,
       nf.provider_id AS nfo_id
FROM media_items mi
JOIN media_provider_ids db ON db.media_id=mi.id
LEFT JOIN nfo_provider_ids nf
       ON nf.media_id=mi.id AND nf.provider=db.provider
WHERE nf.provider_id IS NULL OR nf.provider_id<>db.provider_id;
```

### Alle Filme eines Genres
```sql
SELECT mi.title, mi.year, mi.path
FROM media_items mi
JOIN media_item_values miv ON miv.media_id=mi.id
JOIN metadata_values mv ON mv.id=miv.value_id
WHERE mi.active=1 AND mi.item_type='movie'
  AND mv.kind='genre' AND lower(mv.value)=lower('Action')
ORDER BY mi.title;
```

### Medien mit einer Person
```sql
SELECT p.name, mp.role_type, mp.character_name, mi.title, mi.path
FROM media_people mp
JOIN people p ON p.id=mp.person_id
JOIN media_items mi ON mi.id=mp.media_id
WHERE lower(p.name) LIKE lower('%Name%')
ORDER BY p.name, mi.title;
```

### Filmreihen und Mitglieder
```sql
SELECT c.name AS collection, cm.sort_order, mi.title, mi.year
FROM collection_members cm
JOIN collections c ON c.id=cm.collection_id
JOIN media_items mi ON mi.id=cm.media_id
ORDER BY c.name, cm.sort_order, mi.year;
```
"""


def _schema_rows(conn: sqlite3.Connection) -> list[tuple[str, list[sqlite3.Row]]]:
    names = [
        str(row["name"])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    ]
    return [(name, conn.execute(f'PRAGMA table_info("{name}")').fetchall()) for name in names]


def build_schema_help(db_path: str | Path) -> str:
    db = initialize_database(db_path)
    lines = [
        "# DragonTools Mediathek – SQL-Hilfe und Datenbankschema",
        "",
        _SQL_REFERENCE.strip(),
        "",
        "## Tabellen und Attribute",
        "",
    ]
    with closing(_connect(db)) as conn:
        for table, columns in _schema_rows(conn):
            lines.append(f"### {table}")
            description = _TABLE_DESCRIPTIONS.get(table)
            if description:
                lines.append(description)
            lines.append("")
            lines.append("| Spalte | Typ | Pflicht | Schlüssel | Hinweis |")
            lines.append("|---|---|---|---|---|")
            for column in columns:
                name = str(column["name"])
                col_type = str(column["type"] or "")
                required = "ja" if int(column["notnull"] or 0) else "nein"
                key = "PK" if int(column["pk"] or 0) else ""
                hint = _COLUMN_HINTS.get((table, name), "")
                lines.append(f"| `{name}` | `{col_type}` | {required} | {key} | {hint} |")
            lines.append("")
    lines.extend(["", _EXAMPLES.strip(), ""])
    return "\n".join(lines)


def export_schema_help(db_path: str | Path, output_file: str | Path) -> Path:
    target = Path(output_file)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(build_schema_help(db_path), encoding="utf-8")
    return target
