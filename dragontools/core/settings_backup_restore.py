from __future__ import annotations

import json
import logging
import os
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from .settings_backup_common import (
    SECRET_MODE_ENCRYPTED,
    SECRET_MODE_EXCLUDED,
    SECRET_MODE_LEGACY_PLAINTEXT,
    SECRETS_ENTRY,
    current_sensitive_values,
    dragon_documents_dir,
    is_sensitive_settings_key,
    json_restore,
    read_manifest,
    safe_member_path,
    settings_to_dict,
)
from .settings_backup_crypto import decrypt_sensitive_settings

_LOG = logging.getLogger(__name__)


def restore_backup(
    archive_path: str | Path,
    *,
    settings,
    documents_dir: Path | None = None,
    clear_settings: bool = True,
    password: str | None = None,
    restore_legacy_plaintext_secrets: bool = True,
) -> dict[str, Any]:
    root = documents_dir or dragon_documents_dir()
    restored_files: list[str] = []
    archive = Path(archive_path)

    settings_data, manifest, secret_mode, preserved_sensitive, pending_files = _load_restore_payload(
        archive,
        settings=settings,
        root=root,
        password=password,
        restore_legacy_plaintext_secrets=restore_legacy_plaintext_secrets,
    )

    settings_snapshot = settings_to_dict(settings)
    file_snapshots: dict[Path, bytes | None] = {
        target: target.read_bytes() if target.exists() and target.is_file() else None
        for target, _content in pending_files
    }

    try:
        if clear_settings:
            settings.clear()
        for key, value in settings_data.items():
            settings.setValue(str(key), json_restore(value))
        for key, value in preserved_sensitive.items():
            settings.setValue(str(key), value)

        for target, content in pending_files:
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(target, content)
            restored_files.append(str(target))
        settings.sync()
    except Exception:
        restore_settings_snapshot(settings, settings_snapshot)
        restore_file_snapshots(file_snapshots)
        raise

    return {
        "manifest": manifest,
        "restored_files": restored_files,
        "secret_mode": secret_mode,
        "legacy_plaintext_secrets_restored": bool(
            secret_mode == SECRET_MODE_LEGACY_PLAINTEXT and restore_legacy_plaintext_secrets
        ),
    }


def _load_restore_payload(
    archive: Path,
    *,
    settings,
    root: Path,
    password: str | None,
    restore_legacy_plaintext_secrets: bool,
) -> tuple[dict[str, Any], dict[str, Any], str, dict[str, Any], list[tuple[Path, bytes]]]:
    # Erst vollständig lesen/entschlüsseln/validieren. Ein falsches Passwort darf
    # aktuelle QSettings niemals teilweise verändern.
    with zipfile.ZipFile(archive, "r") as zf:
        manifest = read_manifest(zf)
        secret_info = manifest.get("secrets") or {}
        secret_mode = str(secret_info.get("mode") or SECRET_MODE_LEGACY_PLAINTEXT)
        if secret_mode not in {SECRET_MODE_EXCLUDED, SECRET_MODE_ENCRYPTED, SECRET_MODE_LEGACY_PLAINTEXT}:
            raise ValueError(f"Unbekannter Secret-Modus im Backup: {secret_mode}")

        try:
            settings_data = json.loads(zf.read("settings.json").decode("utf-8"))
        except KeyError as exc:
            raise ValueError("Ungültiges DragonTools-Backup: settings.json fehlt.") from exc
        if not isinstance(settings_data, dict):
            raise ValueError("Ungültige settings.json im Backup.")

        if secret_mode == SECRET_MODE_ENCRYPTED:
            try:
                encrypted_payload = zf.read(SECRETS_ENTRY)
            except KeyError as exc:
                raise ValueError("Verschlüsselte Zugangsdaten fehlen im Backup.") from exc
            settings_data.update(decrypt_sensitive_settings(encrypted_payload, password))

        preserve_sensitive = secret_mode == SECRET_MODE_EXCLUDED or (
            secret_mode == SECRET_MODE_LEGACY_PLAINTEXT and not restore_legacy_plaintext_secrets
        )
        preserved_sensitive = current_sensitive_values(settings) if preserve_sensitive else {}
        if preserve_sensitive:
            settings_data = {
                key: value for key, value in settings_data.items()
                if not is_sensitive_settings_key(str(key))
            }

        pending_files: list[tuple[Path, bytes]] = []
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if info.is_dir() or not name.startswith("files/"):
                continue
            if name.startswith("files/rules/"):
                relative = "rules/" + Path(name).name
            elif name.startswith("files/profiles/"):
                relative = Path(name).name
            else:
                continue
            target = safe_member_path(root, relative)
            if target is not None:
                pending_files.append((target, zf.read(info)))
    return settings_data, manifest, secret_mode, preserved_sensitive, pending_files


def restore_settings_snapshot(settings, snapshot: dict[str, Any]) -> None:
    try:
        settings.clear()
        for key, value in snapshot.items():
            settings.setValue(str(key), json_restore(value))
        settings.sync()
    except Exception:
        _LOG.exception("QSettings-Rollback nach fehlgeschlagenem Restore ist fehlgeschlagen.")


def restore_file_snapshots(snapshots: dict[Path, bytes | None]) -> None:
    for target, content in snapshots.items():
        try:
            if content is None:
                if target.exists() and target.is_file():
                    target.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(target, content)
        except Exception:
            _LOG.exception("Datei-Rollback nach fehlgeschlagenem Restore ist fehlgeschlagen: %s", target)


def atomic_write_bytes(path: Path, content: bytes) -> None:
    token = f"{os.getpid()}_{datetime.now().strftime('%H%M%S_%f')}"
    tmp = path.with_name(f"{path.name}.{token}.tmp")
    try:
        tmp.write_bytes(content)
        os.replace(str(tmp), str(path))
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception as cleanup_exc:
            _LOG.warning("Temporäre Restore-Datei konnte nicht entfernt werden: %s (%s)", tmp, cleanup_exc)
        raise
