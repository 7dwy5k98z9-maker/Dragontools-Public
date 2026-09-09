from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .media_library_paths import _has_prefix, _normalize_slashes, get_path_mappings
from .media_library_types import PathMapping
from .media_library_utils import _normalize_title
from .paths import normalize_user_path

def _path_norm_sql(alias: str = "mi") -> str:
    return f"lower(replace(coalesce({alias}.path, ''), char(92), '/'))"


def _path_prefix_condition(prefixes: Iterable[str], params: list[Any]) -> str:
    conditions: list[str] = []
    path_expr = _path_norm_sql("mi")
    for prefix in prefixes:
        norm = _normalize_slashes(normalize_user_path(str(prefix))).casefold().rstrip("/")
        if not norm:
            continue
        conditions.append(f"({path_expr}=? OR {path_expr} LIKE ?)")
        params.extend([norm, norm + "/%"])
    return "(" + " OR ".join(conditions) + ")" if conditions else ""


def _mapping_prefixes_for_scope(db_path: Path, scope: str) -> list[str]:
    try:
        mappings = get_path_mappings(db_path)
    except Exception:
        mappings = []
    wanted = scope.casefold()
    if wanted in {"movies", "filme", "film"}:
        labels = {"filme", "film", "movies", "movie"}
    elif wanted == "anime":
        labels = {"anime"}
    elif wanted in {"tv", "series", "serien"}:
        labels = {"tv", "tvserien", "serien", "series"}
    else:
        labels = {wanted}

    prefixes: list[str] = []
    for mapping in mappings:
        label = _normalize_title(mapping.label)
        external = _normalize_title(mapping.external_prefix.strip("/\\"))
        if label in labels or external in labels:
            prefixes.append(mapping.local_prefix)
    return prefixes


def _area_for_path(path: Any, mappings: Iterable[PathMapping]) -> str:
    text = str(path or "")
    for mapping in mappings:
        if _has_prefix(text, mapping.local_prefix) or _has_prefix(text, mapping.external_prefix):
            return mapping.label or mapping.external_prefix.strip("/\\") or "Mapping"
    lowered = _normalize_slashes(text).casefold()
    if "/filme/" in lowered or lowered.endswith("/filme"):
        return "Filme"
    if "/serien/anime/" in lowered or lowered.endswith("/anime"):
        return "Anime"
    if "/serien/tv/" in lowered or lowered.endswith("/tv"):
        return "TV"
    return ""
