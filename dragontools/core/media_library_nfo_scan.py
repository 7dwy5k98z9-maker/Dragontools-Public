from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from .media_library_db import _connect, backup_database, initialize_database
from .media_library_nfo_inventory import _candidate_rows, _inspect_nfo_candidate
from .media_library_nfo_parser import (
    _child_text,
    _int_text,
    _nfo_type_for_root,
    _provider_ids,
    parse_nfo,
)
from .media_library_nfo_paths import (
    _candidate_nfo_paths,
    _find_nfo,
    _media_directory,
    _media_directory_reachable,
    _path_is_directory,
)
from .media_library_nfo_store import (
    _apply_nfo_scan_batch,
    _mark_parse_error,
    _normalize_text,
    _replace_nfo_issues,
    _store_parsed_nfo,
)
from .media_library_types import AbortFn, LibraryLightScanResult, LogFn, ProgressFn

_NFO_SCAN_WRITE_BATCH = 100


def scan_nfo_inventory(
    db_path: str | Path,
    *,
    full_audit: bool = False,
    backup: bool = True,
    logger: LogFn = None,
    progress: ProgressFn = None,
    should_abort: AbortFn = None,
) -> LibraryLightScanResult:
    db = initialize_database(db_path)
    with closing(_connect(db)) as conn:
        candidates = _candidate_rows(conn, full_audit=full_audit)

    if candidates and backup:
        backup_database(db, "pre_nfo_lightscan")

    counters = _NfoScanCounters()
    warnings: list[str] = []
    pending: list[tuple[sqlite3.Row, dict[str, object]]] = []

    with closing(_connect(db)) as conn:
        total = len(candidates)
        for index, row in enumerate(candidates, start=1):
            if should_abort and should_abort():
                counters.aborted = True
                break
            media_path = str(row["path"] or "")
            if progress:
                progress(index, total, media_path)

            result = _inspect_nfo_candidate(row)
            counters.record(str(result.get("status") or "invalid"))
            warning = str(result.get("warning") or "")
            if warning:
                warnings.append(warning)
            pending.append((row, result))

            # NAS/XML access happens before this point, with no writer transaction open.
            if len(pending) >= _NFO_SCAN_WRITE_BATCH:
                counters.issues += _apply_nfo_scan_batch(conn, pending)
                pending.clear()

        if pending:
            counters.issues += _apply_nfo_scan_batch(conn, pending)

    if logger:
        logger(counters.summary(len(candidates)))
    return LibraryLightScanResult(
        db_path=db,
        candidates=len(candidates),
        scanned_items=counters.scanned,
        nfo_present=counters.present,
        nfo_missing=counters.missing,
        nfo_unreachable=counters.unreachable,
        nfo_invalid=counters.invalid,
        issues=counters.issues,
        aborted=counters.aborted,
        warnings=tuple(warnings),
    )


class _NfoScanCounters:
    __slots__ = ("present", "missing", "unreachable", "invalid", "issues", "scanned", "aborted")

    def __init__(self) -> None:
        self.present = 0
        self.missing = 0
        self.unreachable = 0
        self.invalid = 0
        self.issues = 0
        self.scanned = 0
        self.aborted = False

    def record(self, status: str) -> None:
        self.scanned += 1
        if status == "present":
            self.present += 1
        elif status == "missing":
            self.missing += 1
        elif status == "unreachable":
            self.unreachable += 1
        else:
            self.invalid += 1

    def summary(self, candidates: int) -> str:
        return (
            f"NFO-Lightscan: {self.scanned}/{candidates} geprüft, {self.present} vorhanden, "
            f"{self.missing} fehlend, {self.unreachable} nicht erreichbar, "
            f"{self.invalid} fehlerhaft, {self.issues} Abweichungen."
        )


__all__ = ["parse_nfo", "scan_nfo_inventory"]
