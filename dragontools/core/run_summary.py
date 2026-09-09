from __future__ import annotations

from pathlib import Path
from typing import Any


OK_STATUS = "ok"
ERROR_STATUS = "error"
SKIPPED_STATUS = "skipped"


def _status_key(status: str) -> str:
    text = str(status or "").strip().lower()
    if text in {"ok", "success", "done", "✅"}:
        return OK_STATUS
    if text in {"skip", "skipped", "⏭", "⏭️"}:
        return SKIPPED_STATUS
    if text in {"warn", "warning", "⚠", "⚠️"}:
        return ERROR_STATUS
    return ERROR_STATUS


def _path_name(path: str | None) -> str:
    return Path(path).name if path else ""


def _size_of(path: str | None) -> int:
    if not path:
        return 0
    try:
        p = Path(path)
        return p.stat().st_size if p.exists() else 0
    except Exception:
        return 0


def _fmt_size(value: int) -> str:
    sign = "-" if value < 0 else ""
    n = abs(int(value or 0))
    units = ["B", "KB", "MB", "GB", "TB"]
    amount = float(n)
    unit = units[0]
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            break
        amount /= 1024.0
    if unit == "B":
        return f"{sign}{int(amount)} {unit}"
    return f"{sign}{amount:.2f} {unit}"


def _sidecar_kind(path: str) -> str:
    p = Path(path)
    if p.suffix.lower() == ".nfo":
        return "nfo"
    if p.suffix.lower() == ".trickplay" or str(path).lower().endswith(".trickplay"):
        return "trickplay"
    return "subtitle"


def _sidecar_label(sidecars: list[str]) -> str:
    if not sidecars:
        return "keine"
    counts = {"subtitle": 0, "nfo": 0, "trickplay": 0}
    for path in sidecars:
        counts[_sidecar_kind(str(path))] = counts.get(_sidecar_kind(str(path)), 0) + 1
    parts: list[str] = []
    if counts.get("subtitle"):
        parts.append(f"Untertitel {counts['subtitle']}")
    if counts.get("nfo"):
        parts.append(f"NFO {counts['nfo']}")
    if counts.get("trickplay"):
        parts.append(f"Trickplay {counts['trickplay']}")
    return " | ".join(parts) if parts else str(len(sidecars))


_POSTPROCESS_KIND_LABELS = {
    "nfo": "NFO",
    "trickplay": "Trickplay",
}

_POSTPROCESS_STATUS_LABELS = {
    "created": "erstellt",
    "created_variant": "ergänzt",
    "skipped": "beibehalten",
    "replaced": "ersetzt",
    "backed_up": "gesichert",
    "error": "Fehler",
}


def _postprocess_label(items: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for item in items:
        kind = _POSTPROCESS_KIND_LABELS.get(str(item.get("kind") or ""), str(item.get("kind") or "Zusatzdaten"))
        status = _POSTPROCESS_STATUS_LABELS.get(
            str(item.get("status") or ""),
            str(item.get("status") or "unbekannt"),
        )
        message = str(item.get("message") or "").strip()
        text = f"{kind} {status}"
        if message and status in {"Fehler", "beibehalten"}:
            text += f" ({message})"
        parts.append(text)
    return " | ".join(parts)


def _postprocess_totals(rows: list[dict[str, Any]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for row in rows:
        for item in row.get("postprocess") or []:
            key = f"{item.get('kind') or 'postprocess'}:{item.get('status') or 'unknown'}"
            totals[key] = totals.get(key, 0) + 1
    return totals


def _postprocess_totals_label(totals: dict[str, int]) -> str:
    if not totals:
        return ""
    parts: list[str] = []
    for key in sorted(totals):
        kind, _sep, status = key.partition(":")
        kind_label = _POSTPROCESS_KIND_LABELS.get(kind, kind)
        status_label = _POSTPROCESS_STATUS_LABELS.get(status, status)
        parts.append(f"{kind_label} {status_label}: {totals[key]}")
    return " | ".join(parts)


def normalize_result_row(entry: dict[str, Any]) -> dict[str, Any]:
    input_path = str(entry.get("input_path") or "")
    output_path = str(entry.get("output_path") or "")
    status = _status_key(str(entry.get("status") or ""))
    sidecars = list(entry.get("sidecars") or [])
    postprocess = [dict(item) for item in (entry.get("postprocess") or []) if isinstance(item, dict)]
    sidecar_label = _sidecar_label([str(item) for item in sidecars])
    postprocess_label = _postprocess_label(postprocess)
    return {
        "input_path": input_path,
        "output_path": output_path,
        "status": status,
        "status_label": {"ok": "OK", "error": "Fehler", "skipped": "Übersprungen"}[status],
        "input_name": _path_name(input_path),
        "output_name": _path_name(output_path),
        "sidecar_count": len(sidecars),
        "sidecar_label": sidecar_label,
        "postprocess": postprocess,
        "postprocess_label": postprocess_label,
        "extra_label": " | ".join(part for part in (sidecar_label, postprocess_label) if part and part != "keine")
        or "keine",
        "output_size": _size_of(output_path),
        "message": str(entry.get("message") or ""),
        "error_report": str(entry.get("error_report") or ""),
        "pipeline": str(entry.get("pipeline") or ""),
        "container": str(entry.get("container") or ""),
        "strategy": str(entry.get("strategy") or ""),
    }


def build_run_summary(
    result_entries: list[dict[str, Any]],
    *,
    total_before: int = 0,
    total_after: int = 0,
    move_ok: int = 0,
    move_errors: int = 0,
    archived: int = 0,
) -> dict[str, Any]:
    rows = [normalize_result_row(entry) for entry in result_entries]
    ok = sum(1 for row in rows if row["status"] == OK_STATUS)
    errors = sum(1 for row in rows if row["status"] == ERROR_STATUS)
    skipped = sum(1 for row in rows if row["status"] == SKIPPED_STATUS)
    failed_inputs = [row["input_path"] for row in rows if row["status"] == ERROR_STATUS and row["input_path"]]
    saved_bytes = int(total_before or 0) - int(total_after or 0)
    postprocess_totals = _postprocess_totals(rows)

    return {
        "rows": rows,
        "ok": ok,
        "errors": errors,
        "skipped": skipped,
        "total": len(rows),
        "move_ok": int(move_ok or 0),
        "move_errors": int(move_errors or 0),
        "archived": int(archived or 0),
        "total_before": int(total_before or 0),
        "total_after": int(total_after or 0),
        "saved_bytes": saved_bytes,
        "saved_label": _fmt_size(saved_bytes),
        "total_before_label": _fmt_size(int(total_before or 0)),
        "total_after_label": _fmt_size(int(total_after or 0)),
        "failed_inputs": failed_inputs,
        "has_failures": bool(failed_inputs),
        "postprocess_totals": postprocess_totals,
        "postprocess_summary_label": _postprocess_totals_label(postprocess_totals),
    }
