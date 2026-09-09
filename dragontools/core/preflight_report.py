# -*- coding: utf-8 -*-
"""Speicherbarer Preflight-Bericht für Start- und Verschiebeprüfungen."""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from ..rules.move_rules import parse_series_match_details
from .paths import user_path_name, user_path_stem
from .settings import APP_VERSION


REPORT_DIR_NAME = "PreflightReports"


def default_preflight_report_dir(documents_dir: str | Path | None = None) -> Path:
    """Standardordner für lokal gespeicherte Preflight-Berichte."""
    if documents_dir is None:
        return Path.home() / "Documents" / "DragonTools" / REPORT_DIR_NAME
    return Path(documents_dir) / REPORT_DIR_NAME


def default_preflight_report_path(
    *,
    report_dir: str | Path | None = None,
    created_at: datetime | None = None,
) -> Path:
    created = created_at or datetime.now()
    base = Path(report_dir) if report_dir is not None else default_preflight_report_dir()
    return base / f"{created:%Y%m%d_%H%M%S}_Preflight.txt"


def _text(value: Any, fallback: str = "-") -> str:
    if value is None:
        return fallback
    value = str(value).strip()
    return value or fallback


def _short_path(path: str, max_len: int = 120) -> str:
    value = str(path)
    if len(value) <= max_len:
        return value
    return "..." + value[-(max_len - 3):]


def _planned_target_text(value: Any) -> str:
    if isinstance(value, dict):
        target = _text(value.get("target") or value.get("dir") or value.get("path"))
        subpath = _text(value.get("subpath"), "")
        if subpath:
            return f"{target}  (Unterordner: {subpath})"
        return target
    return _text(value)


def _clean_series_name(value: Any) -> str:
    return re.sub(r"[._]+", " ", _text(value, "")).strip(" -._")


def _classification(path: str) -> str:
    parsed = parse_series_match_details(user_path_name(path))
    if parsed and parsed.get("series"):
        season = parsed.get("season")
        episode = parsed.get("episode")
        episodes = parsed.get("episodes") or []
        if episodes:
            ep_text = ", ".join(f"{int(ep):02d}" for ep in episodes if ep is not None)
        elif episode is not None:
            ep_text = f"{int(episode):02d}"
        else:
            ep_text = "?"
        season_text = f"{int(season):02d}" if season is not None else "?"
        return f"Serie: {_clean_series_name(parsed['series'])} | Staffel {season_text} | Folge {ep_text}"

    fallback = re.search(
        r"(?P<series>.+?)[ ._-]+S(?P<season>\d{1,2})E(?P<episode>\d{1,3})",
        user_path_stem(path),
        flags=re.IGNORECASE,
    )
    if fallback:
        series = _clean_series_name(fallback.group("series"))
        return (
            f"Serie: {series} | "
            f"Staffel {int(fallback.group('season')):02d} | "
            f"Folge {int(fallback.group('episode')):02d}"
        )
    return "Film/Einzeldatei"


def _rows_by_path(rows: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        path = str(row.get("path") or "")
        if path:
            result[path] = row
    return result


def _summary_line(rows: list[dict[str, Any]] | None) -> str:
    if not rows:
        return "Regel-/Systemvorschau: nicht erstellt"
    counts = Counter(str(row.get("severity") or "ok").lower() for row in rows)
    return (
        "Regel-/Systemvorschau: "
        f"OK {counts.get('ok', 0)} | "
        f"Warnung {counts.get('warn', 0)} | "
        f"Fehler {counts.get('error', 0)}"
    )


def _add_row_details(lines: list[str], row: dict[str, Any]) -> None:
    fields = (
        ("video", "Video"),
        ("hdr", "HDR/DV"),
        ("audio", "Audio"),
        ("subtitles", "Untertitel"),
        ("pipeline", "Pipeline"),
        ("target", "Ausgabe"),
    )
    for key, label in fields:
        value = row.get(key)
        if value:
            lines.append(f"   {label}: {_text(value)}")

    status = row.get("status")
    if status:
        lines.append(f"   Status: {_text(status)}")


def _add_warnings(lines: list[str], warnings: list[str]) -> None:
    if not warnings:
        return
    lines.append("   Hinweise:")
    for warning in warnings:
        lines.append(f"   - {_text(warning)}")


def _add_decision_reasons(lines: list[str], reasons: list[str]) -> None:
    if not reasons:
        return
    lines.append("   Entscheidungen:")
    for reason in reasons:
        lines.append(f"   - {_text(reason)}")


def build_preflight_report(
    files: list[str],
    *,
    planned_targets: dict[str, Any] | None = None,
    target_paths: dict[str, str | None] | None = None,
    rows: list[dict[str, Any]] | None = None,
    settings_summary: dict[str, Any] | None = None,
    title: str = "Preflight-Bericht",
    created_at: datetime | None = None,
) -> str:
    """Erzeugt den Textinhalt eines speicherbaren Preflight-Berichts."""
    created = created_at or datetime.now()
    planned = planned_targets or {}
    targets = target_paths or {}
    row_map = _rows_by_path(rows)

    lines: list[str] = [
        f"📋 {title} – Dragon Tools V{APP_VERSION}",
        "=" * 88,
        f"Erstellt: {created:%d.%m.%Y %H:%M:%S} Uhr",
        f"Dateien: {len(files)}",
        _summary_line(rows),
        "=" * 88,
        "",
        "Zielpfade",
        f"- TV: {_text(targets.get('tv'))}",
        f"- Anime: {_text(targets.get('anime'))}",
        f"- Filme: {_text(targets.get('film') or targets.get('filme'))}",
    ]

    if settings_summary:
        lines.extend(["", "Einstellungen"])
        for key, value in settings_summary.items():
            lines.append(f"- {key}: {_text(value)}")

    lines.extend(["", "Dateien"])
    for index, path in enumerate(files, start=1):
        row = row_map.get(path)
        planned_target = planned.get(path)
        warnings = list(row.get("warnings") or []) if row else []
        if not planned_target:
            warnings.append("Kein Zielpfad geplant oder Zielpfad nicht verfügbar.")

        lines.append("")
        lines.append(f"{index:03d}. {user_path_name(path)}")
        lines.append(f"   Quelle: {_short_path(path)}")
        lines.append(f"   Erkennung: {_classification(path)}")
        lines.append(f"   Geplanter Zielordner: {_planned_target_text(planned_target)}")
        if row:
            _add_row_details(lines, row)
            _add_decision_reasons(lines, list(row.get("decision_reasons") or []))
        else:
            lines.append("   Regelvorschau: nicht erstellt")
        _add_warnings(lines, warnings)

    lines.extend(
        [
            "",
            "=" * 88,
            "Hinweis: Dieser Bericht wird nur lokal gespeichert und nicht automatisch versendet.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_preflight_report(
    files: list[str],
    *,
    planned_targets: dict[str, Any] | None = None,
    target_paths: dict[str, str | None] | None = None,
    rows: list[dict[str, Any]] | None = None,
    settings_summary: dict[str, Any] | None = None,
    title: str = "Preflight-Bericht",
    report_dir: str | Path | None = None,
    output_path: str | Path | None = None,
    created_at: datetime | None = None,
) -> Path:
    """Schreibt den Preflight-Bericht und gibt den Dateipfad zurück."""
    created = created_at or datetime.now()
    path = (
        Path(output_path)
        if output_path is not None
        else default_preflight_report_path(report_dir=report_dir, created_at=created)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    text = build_preflight_report(
        files,
        planned_targets=planned_targets,
        target_paths=target_paths,
        rows=rows,
        settings_summary=settings_summary,
        title=title,
        created_at=created,
    )
    path.write_text(text, encoding="utf-8")
    return path
