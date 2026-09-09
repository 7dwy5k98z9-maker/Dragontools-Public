# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path

LOG_CATEGORY_NORMAL = "normal"
LOG_CATEGORY_ERROR = "error"
LOG_CATEGORY_CRASH = "crash"
LOG_CATEGORY_VERBOSE = "verbose"
ALL_LOG_CATEGORIES = (
    LOG_CATEGORY_NORMAL,
    LOG_CATEGORY_ERROR,
    LOG_CATEGORY_CRASH,
    LOG_CATEGORY_VERBOSE,
)


@dataclass
class LogCleanupResult:
    deleted_files: int = 0
    deleted_dirs: int = 0
    skipped_files: int = 0


def cleanup_logs(
    base_root: str | Path,
    *,
    cutoff_date: date | None = None,
    include_verbose: bool = True,
    categories: set[str] | list[str] | tuple[str, ...] | None = None,
) -> LogCleanupResult:
    """Löscht DragonTools-Logdateien unterhalb des konfigurierten Log-Basisordners.

    cutoff_date=None löscht alle Logdateien. Bei gesetztem Datum werden Dateien
    gelöscht, deren Änderungszeit am oder vor diesem Datum liegt.
    """
    root = Path(base_root).expanduser()
    result = LogCleanupResult()
    if not root:
        return result

    selected = set(categories or ALL_LOG_CATEGORIES)
    if not include_verbose:
        selected.discard(LOG_CATEGORY_VERBOSE)

    if selected & {LOG_CATEGORY_NORMAL, LOG_CATEGORY_ERROR, LOG_CATEGORY_CRASH}:
        _cleanup_folder(
            root / "Logging",
            cutoff_date=cutoff_date,
            result=result,
            categories=selected,
        )
    if LOG_CATEGORY_VERBOSE in selected:
        _cleanup_folder(
            root / "VerboseLog",
            cutoff_date=cutoff_date,
            result=result,
            categories={LOG_CATEGORY_VERBOSE},
        )
    return result


def _cleanup_folder(
    folder: Path,
    *,
    cutoff_date: date | None,
    result: LogCleanupResult,
    categories: set[str],
) -> None:
    try:
        resolved_folder = folder.resolve()
    except Exception:
        result.skipped_files += 1
        return
    if not resolved_folder.exists():
        return

    cutoff_dt = (
        datetime.combine(cutoff_date, time.max) if cutoff_date is not None else None
    )
    files = sorted((p for p in resolved_folder.rglob("*") if p.is_file()), key=lambda p: len(p.parts), reverse=True)
    for file_path in files:
        if file_path.name == "crash_state.json":
            result.skipped_files += 1
            continue
        if _file_category(file_path) not in categories:
            result.skipped_files += 1
            continue
        try:
            resolved_file = file_path.resolve()
            if not resolved_file.is_relative_to(resolved_folder):
                result.skipped_files += 1
                continue
            if cutoff_dt is not None:
                modified = datetime.fromtimestamp(resolved_file.stat().st_mtime)
                if modified > cutoff_dt:
                    result.skipped_files += 1
                    continue
            resolved_file.unlink(missing_ok=True)
            result.deleted_files += 1
        except Exception:
            result.skipped_files += 1

    dirs = sorted(
        (p for p in resolved_folder.rglob("*") if p.is_dir()),
        key=lambda p: len(p.parts),
        reverse=True,
    )
    for dir_path in dirs:
        try:
            resolved_dir = dir_path.resolve()
            if resolved_dir == resolved_folder or not resolved_dir.is_relative_to(resolved_folder):
                continue
            resolved_dir.rmdir()
            result.deleted_dirs += 1
        except OSError:
            continue
        except Exception:
            continue


def _file_category(path: Path) -> str:
    parts = {part.lower() for part in path.parts}
    if "verboselog" in parts:
        return LOG_CATEGORY_VERBOSE
    if "errorreports" in parts:
        return LOG_CATEGORY_ERROR
    if "crashreports" in parts:
        return LOG_CATEGORY_CRASH
    return LOG_CATEGORY_NORMAL
