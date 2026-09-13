from __future__ import annotations

import base64
import json
from datetime import datetime
from pathlib import Path
from typing import Any
import zipfile

from .settings import SENSITIVE_SETTINGS_KEYS

BACKUP_FORMAT = "DragonToolsBackup"
BACKUP_FORMAT_VERSION = 2
SECRET_MODE_EXCLUDED = "excluded"
SECRET_MODE_ENCRYPTED = "encrypted"
SECRET_MODE_LEGACY_PLAINTEXT = "legacy_plaintext"
SECRETS_ENTRY = "secrets.enc"


class BackupEncryptionUnavailable(RuntimeError):
    """Die optionale Kryptographie-Abhängigkeit ist nicht installiert."""


class BackupPasswordRequired(ValueError):
    """Das gewählte Backup benötigt ein Passwort."""


class InvalidBackupPassword(ValueError):
    """Das Passwort ist falsch oder der verschlüsselte Secret-Block beschädigt."""


def dragon_documents_dir() -> Path:
    return Path.home() / "Documents" / "DragonTools"


def default_backup_dir(documents_dir: Path | None = None) -> Path:
    root = documents_dir or dragon_documents_dir()
    path = root / "Backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_backup_path(documents_dir: Path | None = None, *, prefix: str = "DragonTools_Backup") -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return default_backup_dir(documents_dir) / f"{prefix}_{stamp}.zip"


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (bytes, bytearray)):
        return {"__bytes_b64__": base64.b64encode(bytes(value)).decode("ascii")}
    try:
        if type(value).__name__ == "QByteArray":
            return {"__bytes_b64__": base64.b64encode(bytes(value)).decode("ascii")}
    except Exception:
        pass
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_safe(val) for key, val in value.items()}
    return str(value)


def json_restore(value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {"__bytes_b64__"}:
        try:
            return base64.b64decode(str(value["__bytes_b64__"]))
        except Exception:
            return b""
    if isinstance(value, list):
        return [json_restore(item) for item in value]
    if isinstance(value, dict):
        return {key: json_restore(val) for key, val in value.items()}
    return value


def is_sensitive_settings_key(key: str) -> bool:
    normalized = str(key).lower()
    if normalized in {item.lower() for item in SENSITIVE_SETTINGS_KEYS}:
        return True
    sensitive_markers = (
        "api_key", "apikey", "access_token", "read_access_token",
        "bearer_token", "secret", "password",
    )
    return any(marker in normalized for marker in sensitive_markers)


def settings_to_dict(settings, *, mask_sensitive: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in sorted(settings.allKeys()):
        key_str = str(key)
        if mask_sensitive and is_sensitive_settings_key(key_str):
            result[key_str] = "********"
        else:
            result[key_str] = json_safe(settings.value(key))
    return result


def partition_settings(settings) -> tuple[dict[str, Any], dict[str, Any]]:
    normal: dict[str, Any] = {}
    sensitive: dict[str, Any] = {}
    for key in sorted(settings.allKeys()):
        key_str = str(key)
        target = sensitive if is_sensitive_settings_key(key_str) else normal
        target[key_str] = json_safe(settings.value(key))
    return normal, sensitive


def iter_backup_files(root: Path) -> list[tuple[Path, str]]:
    files: list[tuple[Path, str]] = []
    rules_dir = root / "rules"
    if rules_dir.exists():
        for path in sorted(rules_dir.glob("*.json")):
            files.append((path, f"files/rules/{path.name}"))
    for path in sorted(root.glob("*_profiles.json")):
        files.append((path, f"files/profiles/{path.name}"))
    return files


def read_manifest(zf: zipfile.ZipFile) -> dict[str, Any]:
    try:
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    except KeyError as exc:
        raise ValueError("Keine DragonTools-Backup-Datei: manifest.json fehlt.") from exc
    if manifest.get("format") != BACKUP_FORMAT:
        raise ValueError("Keine DragonTools-Backup-Datei.")
    return manifest


def safe_member_path(root: Path, member_name: str) -> Path | None:
    parts = Path(member_name).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return None
    target = root.joinpath(*parts).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None
    return target


def current_sensitive_values(settings) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in settings.allKeys():
        key_str = str(key)
        if is_sensitive_settings_key(key_str):
            result[key_str] = settings.value(key)
    return result
