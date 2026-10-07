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
    current_sensitive_storage_values,
    dragon_documents_dir,
    is_sensitive_settings_key,
    json_restore,
    read_manifest,
)
from .settings_backup_crypto import decrypt_sensitive_settings
from .settings_backup_payload import read_configuration_payloads
from .settings_backup_limits import (
    MAX_BACKUP_METADATA_BYTES,
    MAX_BACKUP_SECRET_ENTRY_BYTES,
    read_backup_entry,
    validate_backup_archive,
    validate_backup_path_size,
)
from .secret_settings import write_secret
from .settings_access import (
    raw_settings_snapshot,
    restore_raw_settings_snapshot,
    sync_settings_checked as _sync_settings_checked,
)

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

    # Rollback must preserve the exact persisted representation.  In
    # particular, an undecryptable DPAPI blob is still user data and must not
    # turn into an empty secret during backup restore.
    settings_snapshot = raw_settings_snapshot(settings)
    file_snapshots: dict[Path, bytes | None] = {
        target: target.read_bytes() if target.exists() and target.is_file() else None
        for target, _content in pending_files
    }

    try:
        if clear_settings:
            settings.clear()
        for key, value in settings_data.items():
            key_str = str(key)
            restored = json_restore(value)
            if is_sensitive_settings_key(key_str):
                write_secret(settings, key_str, str(restored or ""))
            else:
                settings.setValue(key_str, restored)
        for key, value in preserved_sensitive.items():
            # ``preserved_sensitive`` contains raw storage values.  Re-running
            # them through write_secret() could double-encrypt DPAPI blobs.
            settings.setValue(str(key), value)

        for target, content in pending_files:
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(target, content)
            restored_files.append(str(target))
        sync_settings_checked(settings)
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
    # Erst vollständig lesen/entschlüsseln/validieren. Ein falsches Passwort oder
    # ein manipuliertes Archiv darf aktuelle QSettings niemals teilweise verändern.
    validate_backup_path_size(archive)
    with zipfile.ZipFile(archive, "r") as zf:
        validate_backup_archive(zf)
        manifest = read_manifest(zf)
        secret_info = manifest.get("secrets") or {}
        secret_mode = str(secret_info.get("mode") or SECRET_MODE_LEGACY_PLAINTEXT)
        if secret_mode not in {SECRET_MODE_EXCLUDED, SECRET_MODE_ENCRYPTED, SECRET_MODE_LEGACY_PLAINTEXT}:
            raise ValueError(f"Unbekannter Secret-Modus im Backup: {secret_mode}")

        try:
            settings_data = json.loads(
                read_backup_entry(zf, "settings.json", max_bytes=MAX_BACKUP_METADATA_BYTES).decode("utf-8")
            )
        except KeyError as exc:
            raise ValueError("Ungültiges DragonTools-Backup: settings.json fehlt.") from exc
        if not isinstance(settings_data, dict):
            raise ValueError("Ungültige settings.json im Backup.")

        format_version = int(manifest.get("format_version", 1))
        if format_version >= 2 and secret_mode in {SECRET_MODE_EXCLUDED, SECRET_MODE_ENCRYPTED}:
            plaintext_secret_keys = [
                str(key) for key in settings_data
                if is_sensitive_settings_key(str(key))
            ]
            if plaintext_secret_keys:
                raise ValueError(
                    "Ungültiges Backup: settings.json enthält bei Secret-Modus "
                    f"'{secret_mode}' sensible Schlüssel im Klartext: "
                    + ", ".join(sorted(plaintext_secret_keys))
                )

        if secret_mode == SECRET_MODE_ENCRYPTED:
            try:
                encrypted_payload = read_backup_entry(
                    zf, SECRETS_ENTRY, max_bytes=MAX_BACKUP_SECRET_ENTRY_BYTES
                )
            except KeyError as exc:
                raise ValueError("Verschlüsselte Zugangsdaten fehlen im Backup.") from exc
            decrypted_secrets = decrypt_sensitive_settings(encrypted_payload, password)
            invalid_secret_keys = [
                str(key) for key in decrypted_secrets
                if not is_sensitive_settings_key(str(key))
            ]
            if invalid_secret_keys:
                raise ValueError(
                    "Ungültiges Backup: secrets.enc enthält nicht-sensitive Einstellungsschlüssel: "
                    + ", ".join(sorted(invalid_secret_keys))
                )
            settings_data.update(decrypted_secrets)

        preserve_sensitive = secret_mode == SECRET_MODE_EXCLUDED or (
            secret_mode == SECRET_MODE_LEGACY_PLAINTEXT and not restore_legacy_plaintext_secrets
        )
        preserved_sensitive = current_sensitive_storage_values(settings) if preserve_sensitive else {}
        if preserve_sensitive:
            settings_data = {
                key: value for key, value in settings_data.items()
                if not is_sensitive_settings_key(str(key))
            }

        pending_files = read_configuration_payloads(zf, root)
    return settings_data, manifest, secret_mode, preserved_sensitive, pending_files


def restore_settings_snapshot(settings, snapshot: dict[str, Any]) -> None:
    try:
        restore_raw_settings_snapshot(settings, snapshot)
    except Exception:
        _LOG.exception("QSettings-Rollback nach fehlgeschlagenem Restore ist fehlgeschlagen.")


def sync_settings_checked(settings) -> None:
    # Backward-compatible import surface for existing tests/callers.
    _sync_settings_checked(settings)


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
        with tmp.open("wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(tmp), str(path))
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception as cleanup_exc:
            _LOG.warning("Temporäre Restore-Datei konnte nicht entfernt werden: %s (%s)", tmp, cleanup_exc)
        raise
