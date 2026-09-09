from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable

from .media_library_db import _connect, initialize_database
from .media_library_types import PathMapping, _now
from .media_library_utils import _normalize_title
from .paths import join_user_path, normalize_user_path, path_compare_key

def load_path_mappings(value: Any) -> list[PathMapping]:
    if not value:
        return []
    if isinstance(value, str):
        try:
            raw = json.loads(value)
        except json.JSONDecodeError:
            return []
    else:
        raw = value
    mappings: list[PathMapping] = []
    if not isinstance(raw, list):
        return mappings
    for item in raw:
        if not isinstance(item, dict):
            continue
        external = str(item.get("external_prefix") or item.get("external") or "").strip()
        local = str(item.get("local_prefix") or item.get("local") or "").strip()
        if not external or not local:
            continue
        mappings.append(
            PathMapping(
                label=str(item.get("label") or "").strip(),
                external_prefix=external,
                local_prefix=local,
            )
        )
    return mappings


def dump_path_mappings(mappings: Iterable[PathMapping]) -> str:
    return json.dumps(
        [
            {
                "label": mapping.label,
                "external_prefix": mapping.external_prefix,
                "local_prefix": mapping.local_prefix,
            }
            for mapping in mappings
        ],
        ensure_ascii=False,
        indent=2,
    )


def save_path_mappings(db_path: str | Path, mappings: Iterable[PathMapping]) -> None:
    initialize_database(db_path)
    with closing(_connect(db_path)) as conn:
        with conn:
            conn.execute("DELETE FROM path_mappings")
            for mapping in mappings:
                conn.execute(
                    """
                    INSERT INTO path_mappings(label, external_prefix, local_prefix, created_at)
                    VALUES(?, ?, ?, ?)
                    """,
                    (mapping.label, mapping.external_prefix, mapping.local_prefix, _now()),
                )
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('updated_at', ?)", (_now(),))


def get_path_mappings(db_path: str | Path) -> list[PathMapping]:
    db = Path(db_path)
    if not db.exists():
        return []
    with closing(_connect(db)) as conn:
        rows = conn.execute(
            "SELECT label, external_prefix, local_prefix FROM path_mappings ORDER BY id"
        ).fetchall()
    return [PathMapping(row["label"], row["external_prefix"], row["local_prefix"]) for row in rows]


def _normalize_slashes(path: str) -> str:
    return (path or "").replace("\\", "/").rstrip("/")


def _has_prefix(path: str, prefix: str) -> bool:
    path_norm = _normalize_slashes(path).casefold()
    prefix_norm = _normalize_slashes(prefix).casefold()
    return path_norm == prefix_norm or path_norm.startswith(prefix_norm + "/")


def _prefix_rest(path: str, prefix: str) -> str | None:
    if not path or not prefix or not _has_prefix(path, prefix):
        return None
    path_norm = _normalize_slashes(path)
    prefix_norm = _normalize_slashes(prefix)
    return path_norm[len(prefix_norm) :].lstrip("/")


def _join_mapped_path(root: str, rest: str) -> str:
    local = normalize_user_path(root)
    if not rest:
        return local
    parts = [part for part in _normalize_slashes(rest).split("/") if part]
    return join_user_path(local, *parts)


def _mapping_identity(mapping: PathMapping) -> tuple[str, str]:
    label = _normalize_title(mapping.label)
    external = _normalize_slashes(mapping.external_prefix).strip("/").casefold()
    return label, external


def _area_key(value: str | None) -> str:
    text = _normalize_title(value)
    if text in {"anime", "animes"}:
        return "anime"
    if text in {"tv", "tvserien", "tv serien", "serien", "serie"}:
        return "tv"
    if text in {"filme", "film", "movies", "movie"}:
        return "movies"
    return ""


def _area_label(area: str) -> str:
    return {"anime": "Anime", "tv": "TV", "movies": "Filme"}.get(area, "")


def _area_from_path_components(path: str) -> str:
    parts = [_area_key(part) for part in _normalize_slashes(path).split("/") if part]
    if "anime" in parts:
        return "anime"
    if "tv" in parts:
        return "tv"
    if "movies" in parts:
        return "movies"
    return ""


def _area_from_root(root: str, mappings: Iterable[PathMapping]) -> str:
    text = str(root or "")
    for mapping in mappings:
        if _has_prefix(text, mapping.local_prefix) or _has_prefix(text, mapping.external_prefix):
            area = _area_key(mapping.label) or _area_key(mapping.external_prefix.strip("/\\"))
            if area:
                return area
    return _area_from_path_components(text)


def _matching_current_mappings(stored: PathMapping, current_mappings: list[PathMapping]) -> list[PathMapping]:
    stored_label, stored_external = _mapping_identity(stored)
    matches: list[PathMapping] = []
    for current in current_mappings:
        current_label, current_external = _mapping_identity(current)
        same_label = bool(stored_label and current_label and stored_label == current_label)
        same_external = bool(stored_external and current_external and stored_external == current_external)
        if same_label or same_external:
            matches.append(current)
    return matches


def _mapping_candidates_from_search_bases(search_bases: Iterable[tuple[str, str]]) -> list[PathMapping]:
    """Leitet aktuelle Move-Ziel-Mappings aus den Preflight-Basisordnern ab."""
    external_by_label = {
        "anime": "/Anime",
        "tv": "/TVSerien",
        "tvserien": "/TVSerien",
        "serien": "/TVSerien",
        "filme": "/Filme",
        "film": "/Filme",
        "movies": "/Filme",
    }
    result: list[PathMapping] = []
    for base, label in search_bases or []:
        local = str(base or "").strip()
        if not local:
            continue
        label_text = str(label or "").strip()
        external = external_by_label.get(_normalize_title(label_text), f"/{label_text}" if label_text else "")
        if not external:
            continue
        result.append(PathMapping(label_text, external, local))
    return result


def _unique_mappings(mappings: Iterable[PathMapping]) -> list[PathMapping]:
    result: list[PathMapping] = []
    seen: set[tuple[str, str, str]] = set()
    for mapping in mappings:
        local = normalize_user_path(mapping.local_prefix) if mapping.local_prefix else ""
        if not local:
            continue
        key = (
            _normalize_title(mapping.label),
            _normalize_slashes(mapping.external_prefix).casefold(),
            path_compare_key(local),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(PathMapping(mapping.label, mapping.external_prefix, local))
    return result


def apply_path_mappings(path: str, mappings: Iterable[PathMapping]) -> str:
    if not path:
        return ""
    text = str(path)
    for mapping in sorted(mappings, key=lambda m: len(_normalize_slashes(m.external_prefix)), reverse=True):
        if not _has_prefix(text, mapping.external_prefix):
            continue
        ext_norm = _normalize_slashes(mapping.external_prefix)
        path_norm = _normalize_slashes(text)
        rest = path_norm[len(ext_norm) :].lstrip("/")
        local = normalize_user_path(mapping.local_prefix)
        if rest:
            parts = [part for part in _normalize_slashes(rest).split("/") if part]
            return join_user_path(local, *parts)
        return local
    return normalize_user_path(text)


def _matches_any_mapping_prefix(path: str, mappings: Iterable[PathMapping]) -> bool:
    mappings_list = list(mappings)
    if not mappings_list:
        return True
    return any(
        _has_prefix(path, mapping.external_prefix) or _has_prefix(path, mapping.local_prefix)
        for mapping in mappings_list
    )
