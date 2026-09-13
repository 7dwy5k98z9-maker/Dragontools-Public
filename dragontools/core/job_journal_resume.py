from __future__ import annotations

import os
from pathlib import Path
from typing import Any

TERMINAL_PROBLEM_STATUSES = {"error", "warn"}
RUNNING_STATUSES = {"running"}
PENDING_STATUSES = {"queued", "unknown", ""}


def normalize_status(status: str) -> str:
    text = str(status or "").strip().lower()
    if "✅" in text or text in {"ok", "success", "done"}:
        return "ok"
    if "⏭" in text or text in {"skip", "skipped"}:
        return "skipped"
    if "⚠" in text or text in {"warn", "warning"}:
        return "warn"
    if "❌" in text or text in {"error", "failed", "fail"}:
        return "error"
    return text or "unknown"


def dedupe_preserve_order(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for path in paths:
        key = os.path.normcase(str(path))
        if key in seen:
            continue
        seen.add(key)
        result.append(str(path))
    return result


def build_resume_plan(
    data: dict[str, Any], *, retry_running: bool = True, retry_failed: bool = False,
) -> dict[str, Any]:
    """Ermittelt aus einem aktiven Journal die Dateien für eine Wiederaufnahme."""
    files = data.get("files") if isinstance(data.get("files"), dict) else {}
    resume_files: list[str] = []
    counts = {"ok": 0, "skipped": 0, "failed": 0, "running": 0, "queued": 0, "unknown": 0}

    for path, row in files.items():
        item = row if isinstance(row, dict) else {}
        status = normalize_status(str(item.get("status") or "queued"))
        if status == "ok":
            counts["ok"] += 1
        elif status == "skipped":
            counts["skipped"] += 1
        elif status in TERMINAL_PROBLEM_STATUSES:
            counts["failed"] += 1
            if retry_failed:
                resume_files.append(str(path))
        elif status in RUNNING_STATUSES:
            counts["running"] += 1
            if retry_running:
                resume_files.append(str(path))
        elif status in PENDING_STATUSES:
            counts["queued"] += 1
            resume_files.append(str(path))
        else:
            counts["unknown"] += 1
            resume_files.append(str(path))

    return {
        "run_id": str(data.get("run_id") or ""),
        "mode": str(data.get("mode") or ""),
        "codec": str(data.get("codec") or "h265").lower(),
        "encoder": str(data.get("encoder") or ""),
        "log_file": str(data.get("log_file") or ""),
        "started_at": str(data.get("started_at") or ""),
        "updated_at": str(data.get("updated_at") or ""),
        "current_file": str(data.get("current_file") or ""),
        "current_files": [str(path) for path in data.get("current_files") or [] if str(path or "")],
        "files": dedupe_preserve_order(resume_files),
        "counts": counts,
        "total_files": len(files),
        "retry_running": bool(retry_running),
        "retry_failed": bool(retry_failed),
    }


def format_unfinished_job_summary(data: dict[str, Any]) -> str:
    files = data.get("files") if isinstance(data.get("files"), dict) else {}
    done = sum(1 for item in files.values() if str(item.get("status") or "") in {"ok", "error", "warn", "skipped"})
    ok = sum(1 for item in files.values() if str(item.get("status") or "") == "ok")
    errors = sum(1 for item in files.values() if str(item.get("status") or "") in {"error", "warn"})
    current_files = [str(path) for path in data.get("current_files") or [] if str(path or "")]
    current = str(data.get("current_file") or "")
    if current and current not in current_files:
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
