from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .batch_preflight_storage import filesystem_preflight, format_gb
from .batch_preflight_decisions import _decision_reasons, _warnings_for
from .batch_preflight_formatting import (
    _audio_summary, _hdr_summary, _pipeline_summary, _profile_summary,
    _subtitle_summary, _target_resolution_summary, _target_summary, _text, _video_summary,
)

PreviewBuilder = Callable[..., dict[str, Any]]
PROBLEM_SEVERITIES = {"warn", "error"}

def _row_from_preview(
    path: str,
    preview: dict[str, Any],
    *,
    codec: str,
    overwrite_original: bool,
    filesystem_checks: bool,
) -> dict[str, Any]:
    warnings, has_error = _warnings_for(path, preview)
    fs_info: dict[str, Any] = {}
    if filesystem_checks:
        fs_info, fs_warnings, fs_error = filesystem_preflight(
            path,
            preview,
            codec=codec,
            overwrite_original=overwrite_original,
        )
        warnings.extend(fs_warnings)
        has_error = has_error or fs_error
    severity = "error" if has_error else ("warn" if warnings else "ok")
    return {
        "path": path,
        "name": Path(path).name,
        "severity": severity,
        "problem": severity in PROBLEM_SEVERITIES,
        "status": {"ok": "OK", "warn": "Warnung", "error": "Fehler"}[severity],
        "video": _video_summary(preview),
        "target_resolution": _target_resolution_summary(preview),
        "hdr": _hdr_summary(preview),
        "audio": _audio_summary(preview),
        "subtitles": _subtitle_summary(preview),
        "target": _target_summary(preview, fs_info),
        "pipeline": _pipeline_summary(preview),
        "profile": _profile_summary(preview),
        "warnings": warnings,
        "decision_reasons": _decision_reasons(preview, fs_info),
        "filesystem": fs_info,
        "analysis_source": _text(preview.get("analysis_source"), "Unbekannt"),
        "preview": preview,
    }


def _error_row(path: str, exc: Exception) -> dict[str, Any]:
    message = f"Analyse fehlgeschlagen: {exc}"
    return {
        "path": path,
        "name": Path(path).name,
        "severity": "error",
        "problem": True,
        "status": "Fehler",
        "video": "Analyse fehlgeschlagen",
        "target_resolution": "-",
        "hdr": "-",
        "audio": "-",
        "subtitles": "-",
        "target": "-",
        "pipeline": "-",
        "profile": "-",
        "warnings": [message],
        "decision_reasons": [],
        "analysis_source": "Fehler",
        "preview": {},
    }


def _storage_group_key(path_value: str | None) -> str:
    if not path_value:
        return ""
    p = Path(path_value)
    return (p.drive or p.anchor or str(p.parent)).lower()


def _set_row_problem(row: dict[str, Any], *, error: bool = False) -> None:
    if error:
        row["severity"] = "error"
        row["status"] = "Fehler"
    elif row.get("severity") == "ok":
        row["severity"] = "warn"
        row["status"] = "Warnung"
    row["problem"] = row.get("severity") in PROBLEM_SEVERITIES


def _append_row_warning(row: dict[str, Any], message: str, *, error: bool = False) -> None:
    warnings = list(row.get("warnings") or [])
    if message not in warnings:
        warnings.append(message)
    row["warnings"] = warnings
    _set_row_problem(row, error=error)


def _annotate_batch_storage(rows: list[dict[str, Any]]) -> None:
    groups: dict[str, dict[str, Any]] = {}
    move_groups: dict[str, dict[str, Any]] = {}

    for row in rows:
        fs = dict(row.get("filesystem") or {})
        source_size = int(fs.get("source_size") or 0)
        if source_size <= 0:
            continue

        output_key = _storage_group_key(fs.get("output_dir"))
        if output_key:
            group = groups.setdefault(output_key, {"rows": [], "required": 0, "free": fs.get("free_bytes")})
            group["rows"].append(row)
            group["required"] += source_size
            free = fs.get("free_bytes")
            if isinstance(free, int):
                group["free"] = min(group["free"], free) if isinstance(group.get("free"), int) else free

        move_key = _storage_group_key(fs.get("move_target_dir"))
        if move_key:
            group = move_groups.setdefault(move_key, {"rows": [], "required": 0, "free": fs.get("move_free_bytes")})
            group["rows"].append(row)
            group["required"] += source_size
            free = fs.get("move_free_bytes")
            if isinstance(free, int):
                group["free"] = min(group["free"], free) if isinstance(group.get("free"), int) else free

    for group in list(groups.values()) + list(move_groups.values()):
        free = group.get("free")
        required = int(group.get("required") or 0)
        if not isinstance(free, int) or required <= 0:
            continue
        if free < required:
            message = (
                "Batch-Speicherwarnung: Summe der Quelldateien auf diesem Ziel "
                f"ist größer als der freie Speicher ({format_gb(required)} geplant, {format_gb(free)} frei)."
            )
            for row in group.get("rows") or []:
                _append_row_warning(row, message)


def build_batch_preflight_rows(
    files: list[str],
    *,
    codec: str = "h265",
    file_overrides: dict[str, dict[str, Any]] | None = None,
    planned_targets: dict[str, Any] | None = None,
    subtitle_rules: dict[str, Any] | None = None,
    overwrite_original: bool = False,
    filesystem_checks: bool = False,
    tools: Any = None,
    preview_builder: PreviewBuilder | None = None,
    preview_options: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Erstellt die Tabellenzeilen für den Batch-Preflight.

    Der Default-Preview-Builder wird absichtlich lazy importiert, damit dieser
    reine Kern auch ohne PyQt6 getestet werden kann.
    """
    if preview_builder is None:
        from .rules_preview import build_rules_preview as preview_builder

    overrides = file_overrides or {}
    targets = planned_targets or {}
    rows: list[dict[str, Any]] = []

    for path in files:
        try:
            preview = preview_builder(
                path,
                codec=codec,
                file_override=overrides.get(path),
                planned_target=targets.get(path),
                subtitle_rules=subtitle_rules,
                tools=tools,
                **dict(preview_options or {}),
            )
            rows.append(
                _row_from_preview(
                    path,
                    preview,
                    codec=codec,
                    overwrite_original=overwrite_original,
                    filesystem_checks=filesystem_checks,
                )
            )
        except Exception as exc:
            rows.append(_error_row(path, exc))

    if filesystem_checks:
        _annotate_batch_storage(rows)

    return rows


def split_problem_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ok_rows = [row for row in rows if row.get("severity") == "ok"]
    problem_rows = [row for row in rows if row.get("severity") != "ok"]
    return ok_rows, problem_rows
