from __future__ import annotations

from pathlib import Path
from typing import Any

from .path_syntax import path_compare_key

from copy import deepcopy
from .job_resume_selection import (TERMINAL_PROBLEM_STATUSES, RUNNING_STATUSES,
    PENDING_STATUSES, normalize_status, dedupe_preserve_order, row_for_path as _row_for_path,
    count_statuses, select_resume_files)


def build_resume_plan(
    data: dict[str, Any], *, retry_running: bool = True, retry_failed: bool = False,
) -> dict[str, Any]:
    """Ermittelt aus einem aktiven Journal die Dateien für eine Wiederaufnahme."""
    files = data.get("files") if isinstance(data.get("files"), dict) else {}
    counts = count_statuses(files)
    resume_files = select_resume_files(data, files, retry_running=retry_running, retry_failed=retry_failed)

    raw_overrides = data.get("file_overrides") if isinstance(data.get("file_overrides"), dict) else {}
    resume_overrides: dict[str, dict] = {}
    for path in resume_files:
        raw = _row_for_path(raw_overrides, path)
        if raw:
            resume_overrides[path] = deepcopy(raw)

    return {
        "run_id": str(data.get("run_id") or ""),
        "journal_path": str(data.get("_journal_path") or ""),
        "mode": str(data.get("mode") or ""),
        "codec": str(data.get("codec") or "h265").lower(),
        "encoder": str(data.get("encoder") or ""),
        "log_file": str(data.get("log_file") or ""),
        "started_at": str(data.get("started_at") or ""),
        "updated_at": str(data.get("updated_at") or ""),
        "current_file": str(data.get("current_file") or ""),
        "current_files": [str(path) for path in data.get("current_files") or [] if str(path or "")],
        "files": dedupe_preserve_order(resume_files),
        "file_overrides": resume_overrides,
        "counts": counts,
        "total_files": len(files),
        "retry_running": bool(retry_running),
        "retry_failed": bool(retry_failed),
    }


def format_unfinished_job_summary(data: dict[str, Any]) -> str:
    files = data.get("files") if isinstance(data.get("files"), dict) else {}
    counts = count_statuses(files)
    done = counts['ok'] + counts['failed'] + counts['skipped']
    ok = counts['ok']
    errors = counts['failed']
    current_files = dedupe_preserve_order(
        [str(path) for path in data.get("current_files") or [] if str(path or "")]
    )
    current = str(data.get("current_file") or "")
    if current and path_compare_key(current) not in {path_compare_key(path) for path in current_files}:
        current_files.append(current)
    lines = [
        f"Run-ID: {data.get('run_id', '-')}",
        f"Gestartet: {data.get('started_at', '-')}",
        f"Modus: {data.get('mode', '-')}",
        f"Codec: {data.get('codec', '-')}",
        f"Dateien: {done}/{len(files)} bearbeitet, {ok} OK, {errors} Fehler/Warnungen",
    ]
    if current_files:
        if len(current_files) == 1:
            lines.append(f"Letzte Datei: {Path(current_files[0]).name}")
        else:
            preview = ", ".join(Path(path).name for path in current_files[:5])
            suffix = f" (+{len(current_files) - 5})" if len(current_files) > 5 else ""
            lines.append(f"Aktive Dateien: {preview}{suffix}")
    log_file = str(data.get("log_file") or "")
    if log_file:
        lines.append(f"Log-Datei: {log_file}")
    return "\n".join(lines)
