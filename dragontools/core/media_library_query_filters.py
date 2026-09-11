from __future__ import annotations

from typing import Any

from .media_library_utils import _normalize_title


NFO_ISSUE_LEVEL_SQL = """
CASE
    WHEN EXISTS (SELECT 1 FROM nfo_issues ni WHERE ni.media_id=mi.id AND upper(ni.severity)='ERROR') THEN 'ERROR'
    WHEN EXISTS (SELECT 1 FROM nfo_issues ni WHERE ni.media_id=mi.id AND upper(ni.severity)='WARNING') THEN 'WARNING'
    WHEN EXISTS (SELECT 1 FROM nfo_issues ni WHERE ni.media_id=mi.id AND upper(ni.severity)='INFO') THEN 'INFO'
    ELSE ''
END
""".strip()

_NFO_PRESET_PREDICATES = {
    "nfo_present": "lower(coalesce(mi.nfo_status, 'unknown'))='present'",
    "nfo_missing": "lower(coalesce(mi.nfo_status, 'unknown'))='missing'",
    "nfo_unreachable": "lower(coalesce(mi.nfo_status, 'unknown'))='unreachable'",
    "nfo_invalid": "lower(coalesce(mi.nfo_status, 'unknown')) IN ('invalid', 'unreadable')",
    "nfo_unknown": "lower(coalesce(mi.nfo_status, 'unknown'))='unknown'",
    "nfo_has_issues": "EXISTS (SELECT 1 FROM nfo_issues ni WHERE ni.media_id=mi.id)",
    "nfo_errors": "EXISTS (SELECT 1 FROM nfo_issues ni WHERE ni.media_id=mi.id AND upper(ni.severity)='ERROR')",
    "nfo_warnings": "EXISTS (SELECT 1 FROM nfo_issues ni WHERE ni.media_id=mi.id AND upper(ni.severity)='WARNING')",
    "nfo_provider_mismatch": (
        "EXISTS (SELECT 1 FROM nfo_issues ni WHERE ni.media_id=mi.id "
        "AND ni.field LIKE 'provider:%' AND upper(ni.severity)='ERROR')"
    ),
}


def append_nfo_filter(preset_key: str, where: list[str]) -> None:
    predicate = _NFO_PRESET_PREDICATES.get(preset_key)
    if predicate:
        where.append(predicate)


def append_text_filter(where: list[str], params: list[Any], text: str) -> None:
    if not text.strip():
        return
    needle = f"%{text.strip().casefold()}%"
    normalized_needle = f"%{_normalize_title(text.strip())}%"
    where.append(
        """
        (
            lower(coalesce(mi.title, '')) LIKE ?
            OR lower(coalesce(mi.original_title, '')) LIKE ?
            OR lower(coalesce(mi.series_title, '')) LIKE ?
            OR lower(coalesce(mi.filename, '')) LIKE ?
            OR lower(coalesce(mi.path, '')) LIKE ?
            OR lower(coalesce(mi.normalized_title, '')) LIKE ?
        )
        """
    )
    params.extend([needle, needle, needle, needle, needle, normalized_needle])
