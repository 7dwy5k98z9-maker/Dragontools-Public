from __future__ import annotations

import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from .settings import APP_VERSION
from .settings_backup_common import (
    BACKUP_FORMAT,
    BACKUP_FORMAT_VERSION,
    SECRET_MODE_ENCRYPTED,
    SECRET_MODE_EXCLUDED,
    SECRET_MODE_LEGACY_PLAINTEXT,
    SECRETS_ENTRY,
    BackupPasswordRequired,
    dragon_documents_dir,
    iter_backup_files,
    partition_settings,
    read_manifest,
)
from .settings_backup_crypto import encrypt_sensitive_settings


def inspect_backup(archive_path: str | Path) -> dict[str, Any]:
    """Liest nur Metadaten und verrät, ob beim Restore ein Passwort nötig ist."""
    with zipfile.ZipFile(Path(archive_path), "r") as zf:
        manifest = read_manifest(zf)
        secret_info = manifest.get("secrets") or {}
        mode = str(secret_info.get("mode") or SECRET_MODE_LEGACY_PLAINTEXT)
        if mode not in {SECRET_MODE_EXCLUDED, SECRET_MODE_ENCRYPTED, SECRET_MODE_LEGACY_PLAINTEXT}:
            raise ValueError(f"Unbekannter Secret-Modus im Backup: {mode}")
        if mode == SECRET_MODE_ENCRYPTED and SECRETS_ENTRY not in zf.namelist():
            raise ValueError("Das Backup meldet verschlüsselte Zugangsdaten, aber secrets.enc fehlt.")
        return {
            "manifest": manifest,
            "secret_mode": mode,
            "requires_password": mode == SECRET_MODE_ENCRYPTED,
        }


def export_backup(
    target_path: str | Path,
    *,
    settings,
    documents_dir: Path | None = None,
    secret_mode: str = SECRET_MODE_EXCLUDED,
    password: str | None = None,
) -> Path:
    root = documents_dir or dragon_documents_dir()
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    if secret_mode not in {SECRET_MODE_EXCLUDED, SECRET_MODE_ENCRYPTED}:
        raise ValueError(f"Unbekannter Secret-Modus: {secret_mode}")
    normal_settings, sensitive_settings = partition_settings(settings)

    secret_manifest: dict[str, Any] = {"mode": secret_mode}
    encrypted_payload: bytes | None = None
    if secret_mode == SECRET_MODE_ENCRYPTED:
        if not password:
            raise BackupPasswordRequired("Für ein verschlüsseltes Backup ist ein Passwort erforderlich.")
        encrypted_payload = encrypt_sensitive_settings(sensitive_settings, password)
        secret_manifest.update({"entry": SECRETS_ENTRY, "cipher": "AES-256-GCM", "kdf": "scrypt"})

    manifest = {
        "format": BACKUP_FORMAT,
        "format_version": BACKUP_FORMAT_VERSION,
        "app_version": APP_VERSION,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "secrets": secret_manifest,
    }
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        zf.writestr("settings.json", json.dumps(normal_settings, indent=2, ensure_ascii=False))
        if encrypted_payload is not None:
            zf.writestr(SECRETS_ENTRY, encrypted_payload)
        for path, arcname in iter_backup_files(root):
            zf.write(path, arcname)
    return target
