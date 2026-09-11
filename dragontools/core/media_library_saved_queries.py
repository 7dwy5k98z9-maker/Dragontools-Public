from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _empty_store() -> dict[str, list[dict[str, Any]]]:
    return {"sql": [], "search": []}


def saved_queries_path(db_path: str | Path) -> Path:
    return Path(db_path).expanduser().resolve(strict=False).parent / "saved_queries.json"


def load_saved_queries(db_path: str | Path) -> dict[str, list[dict[str, Any]]]:
    path = saved_queries_path(db_path)
    if not path.exists():
        return _empty_store()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return _empty_store()
    result = _empty_store()
    for kind in result:
        rows = data.get(kind, []) if isinstance(data, dict) else []
        if isinstance(rows, list):
            result[kind] = [row for row in rows if isinstance(row, dict) and str(row.get("name") or "").strip()]
    return result


def _write_store(db_path: str | Path, data: dict[str, list[dict[str, Any]]]) -> Path:
    path = saved_queries_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)
    return path


def save_named_query(db_path: str | Path, kind: str, name: str, payload: dict[str, Any]) -> Path:
    kind = str(kind or "").strip().casefold()
    if kind not in {"sql", "search"}:
        raise ValueError(f"Unbekannter Abfragetyp: {kind}")
    clean_name = str(name or "").strip()
    if not clean_name:
        raise ValueError("Für eine gespeicherte Abfrage ist ein Name erforderlich.")
    data = load_saved_queries(db_path)
    rows = data[kind]
    entry = {"name": clean_name, **payload}
    for index, row in enumerate(rows):
        if str(row.get("name") or "").casefold() == clean_name.casefold():
            rows[index] = entry
            break
    else:
        rows.append(entry)
    rows.sort(key=lambda row: str(row.get("name") or "").casefold())
    return _write_store(db_path, data)


def delete_named_query(db_path: str | Path, kind: str, name: str) -> Path:
    kind = str(kind or "").strip().casefold()
    if kind not in {"sql", "search"}:
        raise ValueError(f"Unbekannter Abfragetyp: {kind}")
    clean_name = str(name or "").strip().casefold()
    data = load_saved_queries(db_path)
    data[kind] = [
        row for row in data[kind]
        if str(row.get("name") or "").strip().casefold() != clean_name
    ]
    return _write_store(db_path, data)
