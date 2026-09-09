# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
from typing import Any
from .move_journal_contracts import TERMINAL_OK, RETRYABLE
from .move_journal_utils import _normalize_status, _dedupe

def build_move_resume_plan(data: dict[str, Any]) -> dict[str, Any]:
    files = data.get("files") if isinstance(data.get("files"), dict) else {}
    resume_files: list[str] = []
    companion_resume_sources: dict[str, str] = {}
    counts = {"ok": 0, "skipped": 0, "retry": 0}
    for path, row in files.items():
        item = row if isinstance(row, dict) else {}
        status = _normalize_status(item.get("status"))
        if status == "ok":
            counts["ok"] += 1
            continue
        if status == "skipped":
            counts["skipped"] += 1
            continue
        if status in RETRYABLE:
            resume_path = str(path)
            phase = str(item.get("phase") or "")
            dest_path = str(item.get("dest_path") or "")
            # Wenn das Video bereits committed ist, aber Companion/Postprocess
            # noch aussteht, wird bei Recovery die existierende Zieldatei als
            # Queue-Anker verwendet. Der originale Source-Pfad bleibt separat
            # erhalten, damit DB/Journal fachlich korrekt bleiben.
            if phase == "sidecars_pending" and dest_path:
                source_exists = Path(str(path)).exists()
                dest_exists = Path(dest_path).exists()
                if not source_exists and dest_exists:
                    resume_path = dest_path
                    companion_resume_sources[resume_path] = str(path)
            resume_files.append(resume_path)
            counts["retry"] += 1

    planned_targets = data.get("planned_targets")
    if not isinstance(planned_targets, dict):
        planned_targets = {}
    sidecars = data.get("sidecar_outputs_by_video")
    if not isinstance(sidecars, dict):
        sidecars = {}
    target_paths = data.get("target_paths")
    if not isinstance(target_paths, dict):
        target_paths = {}

    # Companion-only Recovery muss Kontext unter dem existierenden Zielvideo
    # bereitstellen, weil die urspruengliche Videodatei bereits verschoben ist.
    if companion_resume_sources:
        planned_targets = dict(planned_targets)
        sidecars = dict(sidecars)
        for resume_path, original_source in companion_resume_sources.items():
            row = files.get(original_source) if isinstance(files.get(original_source), dict) else {}
            if original_source in planned_targets:
                planned_targets[resume_path] = planned_targets[original_source]
            elif row.get("target_dir"):
                planned_targets[resume_path] = {"target_dir": str(row.get("target_dir"))}
            if original_source in sidecars:
                sidecars[resume_path] = list(sidecars.get(original_source) or [])

    return {
        "run_id": str(data.get("run_id") or ""),
        "journal_path": str(data.get("_journal_path") or data.get("journal_path") or ""),
        "files": _dedupe(resume_files),
        "companion_resume_sources": companion_resume_sources,
        "counts": counts,
        "planned_targets": planned_targets,
        "sidecar_outputs_by_video": sidecars,
        "target_paths": target_paths,
        "conflict_mode": str(data.get("conflict_mode") or "skip"),
        "log_file": str(data.get("log_file") or ""),
        "started_at": str(data.get("started_at") or ""),
    }

def format_unfinished_move_summary(data: dict[str, Any]) -> str:
    plan = build_move_resume_plan(data)
    files = data.get("files") if isinstance(data.get("files"), dict) else {}
    lines = [
        f"Run-ID: {data.get('run_id', '-')}",
        f"Gestartet: {data.get('started_at', '-')}",
        f"Dateien gesamt: {len(files)}",
        f"Erfolgreich: {plan['counts'].get('ok', 0)}",
        f"Übersprungen: {plan['counts'].get('skipped', 0)}",
        f"Erneut zu verschieben: {len(plan.get('files') or [])}",
    ]
    current = str(data.get("current_file") or "")
    if current:
        lines.append(f"Zuletzt aktiv: {Path(current).name}")
    log_file = str(data.get("log_file") or "")
    if log_file:
        lines.append(f"Log-Datei: {log_file}")
    ambiguous = sum(
        1
        for row in files.values()
        if isinstance(row, dict) and row.get("recovery_status") == "ambiguous_source_and_destination"
    )
    if ambiguous:
        lines.append(
            f"Recovery-Hinweis: {ambiguous} Datei(en) sind mehrdeutig; Quelle und Ziel existieren, "
            "vorhandene Altbestand-Backups bleiben erhalten."
        )
    return "\n".join(lines)
