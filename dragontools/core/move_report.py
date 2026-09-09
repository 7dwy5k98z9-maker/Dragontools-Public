from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Any


def build_move_target_summary(move_log: list[Any] | None) -> list[dict[str, Any]]:
    """Verdichtet Move-Einträge auf Zielordner-Ebene.

    Neue MoveThread-Versionen liefern Dicts. Alte Tuple-Einträge werden
    weiterhin verstanden, damit bestehende Worker kompatibel bleiben.
    """
    groups: OrderedDict[str, dict[str, Any]] = OrderedDict()

    for entry in move_log or []:
        normalized = _normalize_entry(entry)
        if not normalized:
            continue

        target_dir = normalized["target_dir"] or "Unbekanntes Ziel"
        group = groups.setdefault(
            target_dir,
            {
                "target_dir": target_dir,
                "planned": 0,
                "moved": 0,
                "errors": 0,
                "conflicts": 0,
                "deleted_existing": 0,
                "replaced_existing": 0,
                "renamed": 0,
                "skipped_conflict": 0,
                "sidecars_moved": 0,
                "sidecars_errors": 0,
                "sidecars_by_type": {},
            },
        )

        kind = normalized.get("kind") or "video"
        ok = bool(normalized.get("ok"))

        if kind == "sidecar":
            sidecar_type = _sidecar_type_label(normalized.get("sidecar_type") or "sidecar")
            type_group = group["sidecars_by_type"].setdefault(
                sidecar_type,
                {
                    "ok": 0,
                    "errors": 0,
                    "conflicts": 0,
                    "deleted_existing": 0,
                    "replaced_existing": 0,
                    "backed_up_existing": 0,
                    "renamed": 0,
                    "skipped_conflict": 0,
                },
            )
            if ok:
                group["sidecars_moved"] += 1
                type_group["ok"] += 1
            else:
                group["sidecars_errors"] += 1
                type_group["errors"] += 1
            if normalized.get("conflict"):
                type_group["conflicts"] += 1
            type_group["deleted_existing"] += int(normalized.get("deleted_existing_count") or 0)
            type_group["replaced_existing"] += int(normalized.get("replaced_existing_count") or 0)
            type_group["backed_up_existing"] += int(normalized.get("backed_up_existing_count") or 0)
            if normalized.get("renamed"):
                type_group["renamed"] += 1
            if normalized.get("skipped_conflict"):
                type_group["skipped_conflict"] += 1
        else:
            group["planned"] += 1
            if ok:
                group["moved"] += 1
            else:
                group["errors"] += 1

        if normalized.get("conflict"):
            group["conflicts"] += 1
        group["deleted_existing"] += int(normalized.get("deleted_existing_count") or 0)
        group["replaced_existing"] += int(normalized.get("replaced_existing_count") or 0)
        group["backed_up_existing"] = int(group.get("backed_up_existing") or 0) + int(
            normalized.get("backed_up_existing_count") or 0
        )
        if normalized.get("renamed"):
            group["renamed"] += 1
        if normalized.get("skipped_conflict"):
            group["skipped_conflict"] += 1

    return list(groups.values())


def format_move_target_summary_lines(
    move_log: list[Any] | None,
    *,
    move_ok: int = 0,
    move_errors: int = 0,
) -> list[str]:
    groups = build_move_target_summary(move_log)
    if not groups and move_ok == 0 and move_errors == 0:
        return []

    lines = ["📦  Verschiebebericht"]
    if not groups:
        lines.append(f"✅  Verschoben Gesamt: {move_ok} OK / {move_errors} Fehler")
        return lines

    for group in groups:
        lines.append(f"🎯  Ziel: {group['target_dir']}")
        lines.append(
            "   Dateien: "
            f"{group['planned']} geplant | {group['moved']} verschoben | "
            f"{group['errors']} Fehler"
        )
        lines.append(f"   Zielkonflikte: {group['conflicts']}")
        deleted = int(group["deleted_existing"])
        replaced = int(group["replaced_existing"])
        if deleted or replaced:
            parts = []
            if deleted:
                parts.append(f"{deleted} gelöscht")
            if replaced:
                parts.append(f"{replaced} ersetzt")
            lines.append(f"   Gelöschte/ersetzte Dateien: {deleted + replaced} ({', '.join(parts)})")
        else:
            lines.append("   Gelöschte/ersetzte Dateien: keine")
        if group["renamed"]:
            lines.append(f"   Umbenannt wegen Konflikt: {group['renamed']}")
        if group["skipped_conflict"]:
            lines.append(f"   Wegen Zielkonflikt übersprungen: {group['skipped_conflict']}")
        if group["sidecars_moved"] or group["sidecars_errors"]:
            lines.append(
                "   Sidecars: "
                f"{group['sidecars_moved']} verschoben | {group['sidecars_errors']} Fehler"
            )
            for sidecar_type, data in group.get("sidecars_by_type", {}).items():
                detail_parts = [
                    f"{data['ok']} OK",
                    f"{data['errors']} Fehler",
                ]
                if data.get("conflicts"):
                    detail_parts.append(f"{data['conflicts']} Konflikt(e)")
                if data.get("deleted_existing"):
                    detail_parts.append(f"{data['deleted_existing']} gelöscht")
                if data.get("replaced_existing"):
                    detail_parts.append(f"{data['replaced_existing']} ersetzt")
                if data.get("backed_up_existing"):
                    detail_parts.append(f"{data['backed_up_existing']} gesichert")
                if data.get("renamed"):
                    detail_parts.append(f"{data['renamed']} umbenannt")
                if data.get("skipped_conflict"):
                    detail_parts.append(f"{data['skipped_conflict']} beibehalten")
                lines.append(f"      {sidecar_type}: " + " | ".join(detail_parts))

    lines.append(f"✅  Verschoben Gesamt: {move_ok} OK / {move_errors} Fehler")
    return lines


def _normalize_entry(entry: Any) -> dict[str, Any] | None:
    if isinstance(entry, dict):
        target = str(entry.get("target_dir") or entry.get("folder") or "")
        name = str(entry.get("name") or entry.get("input_name") or "")
        return {
            "kind": str(entry.get("kind") or "video"),
            "sidecar_type": str(entry.get("sidecar_type") or ""),
            "name": name,
            "target_dir": target,
            "ok": bool(entry.get("ok")),
            "conflict": bool(entry.get("conflict")),
            "deleted_existing": bool(entry.get("deleted_existing")),
            "deleted_existing_count": _entry_count(entry, "deleted_existing", "deleted_existing_count"),
            "replaced_existing": bool(entry.get("replaced_existing")),
            "replaced_existing_count": _entry_count(entry, "replaced_existing", "replaced_existing_count"),
            "backed_up_existing": bool(entry.get("backed_up_existing")),
            "backed_up_existing_count": _entry_count(entry, "backed_up_existing", "backed_up_existing_count"),
            "renamed": bool(entry.get("renamed")),
            "skipped_conflict": bool(entry.get("skipped_conflict")),
        }

    if isinstance(entry, tuple) and len(entry) == 2:
        name, folder = entry
        return {
            "kind": "video",
            "sidecar_type": "",
            "name": str(name),
            "target_dir": str(folder),
            "ok": True,
            "conflict": False,
            "deleted_existing": False,
            "deleted_existing_count": 0,
            "replaced_existing": False,
            "replaced_existing_count": 0,
            "backed_up_existing": False,
            "backed_up_existing_count": 0,
            "renamed": False,
            "skipped_conflict": False,
        }

    if isinstance(entry, str) and entry.strip():
        return {
            "kind": "video",
            "sidecar_type": "",
            "name": Path(entry).name,
            "target_dir": "",
            "ok": entry.lstrip().upper().startswith("OK "),
            "conflict": False,
            "deleted_existing": False,
            "deleted_existing_count": 0,
            "replaced_existing": False,
            "replaced_existing_count": 0,
            "backed_up_existing": False,
            "backed_up_existing_count": 0,
            "renamed": False,
            "skipped_conflict": False,
        }

    return None


def _entry_count(entry: dict[str, Any], bool_key: str, count_key: str) -> int:
    value = entry.get(count_key)
    if value is not None:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            pass
    return 1 if entry.get(bool_key) else 0


def _sidecar_type_label(value: str) -> str:
    key = str(value or "").strip().lower()
    return {
        "subtitle": "Untertitel",
        "sub": "Untertitel",
        "nfo": "NFO",
        "trickplay": "Trickplay",
        "sidecar": "Sonstige",
    }.get(key, key.title() if key else "Sonstige")
