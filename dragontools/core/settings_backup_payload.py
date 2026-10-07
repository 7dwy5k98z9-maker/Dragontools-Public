"""Validate configuration file payloads before a backup transaction starts."""
from __future__ import annotations

import json
from pathlib import Path
import zipfile

from .settings_backup_common import safe_member_path
from .settings_backup_limits import read_backup_entry


def _configuration_relative_path(name: str) -> str:
    parts = name.split("/")
    if len(parts) != 3 or parts[0] != "files":
        raise ValueError(f"Ungültiger Datei-Eintrag im Backup: {name}")
    group, filename = parts[1:]
    if not filename or filename in {".", ".."} or ":" in filename:
        raise ValueError(f"Ungültiger Dateiname im Backup: {name}")
    if group == "rules" and filename.casefold().endswith(".json"):
        return "rules/" + filename
    if group == "profiles" and filename.casefold().endswith("_profiles.json"):
        return filename
    raise ValueError(f"Unbekannter Konfigurationsdatei-Eintrag im Backup: {name}")


def read_configuration_payloads(zf: zipfile.ZipFile, root: Path) -> list[tuple[Path, bytes]]:
    pending: list[tuple[Path, bytes]] = []
    for info in zf.infolist():
        name = info.filename.replace("\\", "/")
        if info.is_dir() or not name.startswith("files/"):
            continue
        relative = _configuration_relative_path(name)
        target = safe_member_path(root, relative)
        if target is None:
            raise ValueError(f"Unsicherer Konfigurationspfad im Backup: {name}")
        content = read_backup_entry(zf, info.filename, max_bytes=info.file_size)
        try:
            value = json.loads(content.decode("utf-8-sig"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Ungültige JSON-Konfiguration im Backup: {name}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"Konfiguration im Backup ist kein JSON-Objekt: {name}")
        pending.append((target, content))
    return pending
