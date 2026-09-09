from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

def default_batch_preflight_report_path(documents_dir: Path | None = None) -> Path:
    root = documents_dir or (Path.home() / "Documents" / "DragonTools")
    out_dir = root / "PreflightReports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return out_dir / f"{stamp}_RegelProfilSimulator.txt"


def _report_values(values: list[Any]) -> list[str]:
    return [str(value).strip() for value in values if value is not None and str(value).strip()]


def _report_block(lines: list[str], title: str, values: list[Any], *, fallback: str = "-") -> None:
    items = _report_values(values)
    lines.append(f"{title}:")
    if items:
        lines.extend(f"  - {item}" for item in items)
    else:
        lines.append(f"  - {fallback}")


def format_batch_preflight_report(
    rows: list[dict[str, Any]],
    *,
    title: str = "Regel-/Profil-Simulator aktuelle Queue",
    created_at: datetime | None = None,
) -> str:
    created = created_at or datetime.now()
    ok = sum(1 for row in rows if row.get("severity") == "ok")
    warn = sum(1 for row in rows if row.get("severity") == "warn")
    error = sum(1 for row in rows if row.get("severity") == "error")

    lines = [
        f"{title} - Dragon Tools",
        "=" * 80,
        f"Erstellt: {created.strftime('%d.%m.%Y %H:%M:%S')} Uhr",
        f"Dateien: {len(rows)} | OK: {ok} | Warnungen: {warn} | Fehler: {error}",
        "=" * 80,
        "",
    ]

    for index, row in enumerate(rows, start=1):
        lines.extend([
            f"{index:03d}. {row.get('status', '-')}: {row.get('name', '-')}",
            f"Pfad: {row.get('path', '-')}",
            f"Video: {row.get('video', '-')}",
            f"HDR/DV: {row.get('hdr', '-')}",
            f"Audio: {row.get('audio', '-')}",
            f"Untertitel: {row.get('subtitles', '-')}",
            f"Ziel: {row.get('target', '-')}",
            f"Pipeline: {row.get('pipeline', '-')}",
            f"Profil: {row.get('profile', '-')}",
            f"Analyse: {row.get('analysis_source', '-')}",
        ])
        _report_block(lines, "Entscheidungen", list(row.get("decision_reasons") or []), fallback="Keine Details verfügbar")
        _report_block(lines, "Hinweise", list(row.get("warnings") or []), fallback="Keine")
        lines.extend(["", "-" * 80, ""])

    return "\n".join(lines).rstrip() + "\n"
