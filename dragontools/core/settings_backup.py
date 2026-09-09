from __future__ import annotations

import base64
import json
import logging
import os
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from .settings import APP_VERSION, SENSITIVE_SETTINGS_KEYS


BACKUP_FORMAT = "DragonToolsBackup"
BACKUP_FORMAT_VERSION = 2
SECRET_MODE_EXCLUDED = "excluded"
SECRET_MODE_ENCRYPTED = "encrypted"
SECRET_MODE_LEGACY_PLAINTEXT = "legacy_plaintext"
SECRETS_ENTRY = "secrets.enc"
_AAD = b"DragonToolsBackup:secrets:v1"
_LOG = logging.getLogger(__name__)


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


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (bytes, bytearray)):
        return {"__bytes_b64__": base64.b64encode(bytes(value)).decode("ascii")}
    try:
        type_name = type(value).__name__
        if type_name == "QByteArray":
            return {"__bytes_b64__": base64.b64encode(bytes(value)).decode("ascii")}
    except Exception:
        pass
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(val) for key, val in value.items()}
    return str(value)


def _json_restore(value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {"__bytes_b64__"}:
        try:
            return base64.b64decode(str(value["__bytes_b64__"]))
        except Exception:
            return b""
    if isinstance(value, list):
        return [_json_restore(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_restore(val) for key, val in value.items()}
    return value


def _is_sensitive_settings_key(key: str) -> bool:
    normalized = str(key).lower()
    if normalized in {item.lower() for item in SENSITIVE_SETTINGS_KEYS}:
        return True
    sensitive_markers = (
        "api_key",
        "apikey",
        "access_token",
        "read_access_token",
        "bearer_token",
        "secret",
        "password",
    )
    return any(marker in normalized for marker in sensitive_markers)


def settings_to_dict(settings, *, mask_sensitive: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in sorted(settings.allKeys()):
        key_str = str(key)
        if mask_sensitive and _is_sensitive_settings_key(key_str):
            result[key_str] = "********"
        else:
            result[key_str] = _json_safe(settings.value(key))
    return result


def _partition_settings(settings) -> tuple[dict[str, Any], dict[str, Any]]:
    normal: dict[str, Any] = {}
    sensitive: dict[str, Any] = {}
    for key in sorted(settings.allKeys()):
        key_str = str(key)
        target = sensitive if _is_sensitive_settings_key(key_str) else normal
        target[key_str] = _json_safe(settings.value(key))
    return normal, sensitive


def _iter_backup_files(root: Path) -> list[tuple[Path, str]]:
    files: list[tuple[Path, str]] = []
    rules_dir = root / "rules"
    if rules_dir.exists():
        for path in sorted(rules_dir.glob("*.json")):
            files.append((path, f"files/rules/{path.name}"))
    for path in sorted(root.glob("*_profiles.json")):
        files.append((path, f"files/profiles/{path.name}"))
    return files


def _crypto_primitives():
    try:
        from cryptography.exceptions import InvalidTag
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    except ImportError as exc:  # pragma: no cover - abhängig von Build-Umgebung
        raise BackupEncryptionUnavailable(
            "Für verschlüsselte DragonTools-Backups wird das Python-Paket "
            "'cryptography' benötigt. Bitte cryptography installieren und die App neu bauen."
        ) from exc
    return AESGCM, Scrypt, InvalidTag


def _derive_key(password: str, salt: bytes, *, n: int, r: int, p: int) -> bytes:
    _AESGCM, Scrypt, _InvalidTag = _crypto_primitives()
    kdf = Scrypt(salt=salt, length=32, n=n, r=r, p=p)
    return kdf.derive(password.encode("utf-8"))


def _encrypt_sensitive_settings(data: dict[str, Any], password: str) -> bytes:
    if len(password) < 8:
        raise ValueError("Das Backup-Passwort muss mindestens 8 Zeichen lang sein.")
    AESGCM, _Scrypt, _InvalidTag = _crypto_primitives()
    salt = os.urandom(16)
    nonce = os.urandom(12)
    n, r, p = 2**15, 8, 1
    key = _derive_key(password, salt, n=n, r=r, p=p)
    plaintext = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, _AAD)
    payload = {
        "format": "DragonToolsEncryptedSecrets",
        "version": 1,
        "cipher": "AES-256-GCM",
        "kdf": "scrypt",
        "n": n,
        "r": r,
        "p": p,
        "salt_b64": base64.b64encode(salt).decode("ascii"),
        "nonce_b64": base64.b64encode(nonce).decode("ascii"),
        "ciphertext_b64": base64.b64encode(ciphertext).decode("ascii"),
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _decrypt_sensitive_settings(payload_bytes: bytes, password: str | None) -> dict[str, Any]:
    if not password:
        raise BackupPasswordRequired("Dieses Backup enthält verschlüsselte Zugangsdaten und benötigt ein Passwort.")
    AESGCM, _Scrypt, InvalidTag = _crypto_primitives()
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
        if payload.get("format") != "DragonToolsEncryptedSecrets" or int(payload.get("version", 0)) != 1:
            raise ValueError("Unbekanntes Secret-Format im Backup.")
        if payload.get("cipher") != "AES-256-GCM" or payload.get("kdf") != "scrypt":
            raise ValueError("Nicht unterstützte Backup-Verschlüsselung.")
        salt = base64.b64decode(payload["salt_b64"], validate=True)
        nonce = base64.b64decode(payload["nonce_b64"], validate=True)
        ciphertext = base64.b64decode(payload["ciphertext_b64"], validate=True)
        n = int(payload["n"])
        r = int(payload["r"])
        p = int(payload["p"])
        if n < 2**14 or n > 2**20 or r < 1 or r > 32 or p < 1 or p > 16:
            raise ValueError("Ungültige KDF-Parameter im Backup.")
        key = _derive_key(password, salt, n=n, r=r, p=p)
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, _AAD)
        data = json.loads(plaintext.decode("utf-8"))
    except InvalidTag as exc:
        raise InvalidBackupPassword("Falsches Passwort oder beschädigte verschlüsselte Zugangsdaten.") from exc
    except InvalidBackupPassword:
        raise
    except Exception as exc:
        raise ValueError(f"Verschlüsselte Zugangsdaten konnten nicht gelesen werden: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Ungültiger Secret-Inhalt im Backup.")
    return data


def _read_manifest(zf: zipfile.ZipFile) -> dict[str, Any]:
    try:
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    except KeyError as exc:
        raise ValueError("Keine DragonTools-Backup-Datei: manifest.json fehlt.") from exc
    if manifest.get("format") != BACKUP_FORMAT:
        raise ValueError("Keine DragonTools-Backup-Datei.")
    return manifest


def inspect_backup(archive_path: str | Path) -> dict[str, Any]:
    """Liest nur Metadaten und verrät, ob beim Restore ein Passwort nötig ist."""
    with zipfile.ZipFile(Path(archive_path), "r") as zf:
        manifest = _read_manifest(zf)
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
    normal_settings, sensitive_settings = _partition_settings(settings)

    secret_manifest: dict[str, Any] = {"mode": secret_mode}
    encrypted_payload: bytes | None = None
    if secret_mode == SECRET_MODE_ENCRYPTED:
        if not password:
            raise BackupPasswordRequired("Für ein verschlüsseltes Backup ist ein Passwort erforderlich.")
        encrypted_payload = _encrypt_sensitive_settings(sensitive_settings, password)
        secret_manifest.update({
            "entry": SECRETS_ENTRY,
            "cipher": "AES-256-GCM",
            "kdf": "scrypt",
        })

    manifest = {
        "format": BACKUP_FORMAT,
        "format_version": BACKUP_FORMAT_VERSION,
        "app_version": APP_VERSION,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "secrets": secret_manifest,
    }
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        zf.writestr(
            "settings.json",
            json.dumps(normal_settings, indent=2, ensure_ascii=False),
        )
        if encrypted_payload is not None:
            zf.writestr(SECRETS_ENTRY, encrypted_payload)
        for path, arcname in _iter_backup_files(root):
            zf.write(path, arcname)
    return target


def _safe_member_path(root: Path, member_name: str) -> Path | None:
    parts = Path(member_name).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return None
    target = root.joinpath(*parts).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None
    return target


def _current_sensitive_values(settings) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in settings.allKeys():
        key_str = str(key)
        if _is_sensitive_settings_key(key_str):
            result[key_str] = settings.value(key)
    return result


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

    # Erst vollständig lesen/entschlüsseln/validieren. Dadurch kann ein falsches
    # Passwort die aktuellen QSettings nicht teilweise löschen.
    with zipfile.ZipFile(archive, "r") as zf:
        manifest = _read_manifest(zf)
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
            secret_data = _decrypt_sensitive_settings(encrypted_payload, password)
            settings_data.update(secret_data)

        # Bei neuen Backups ohne Keys und optional bei Legacy-Klartext-Backups
        # bleiben lokal vorhandene Secrets erhalten.
        preserve_sensitive = secret_mode == SECRET_MODE_EXCLUDED or (
            secret_mode == SECRET_MODE_LEGACY_PLAINTEXT
            and not restore_legacy_plaintext_secrets
        )
        preserved_sensitive = _current_sensitive_values(settings) if preserve_sensitive else {}
        if preserve_sensitive:
            settings_data = {
                key: value for key, value in settings_data.items()
                if not _is_sensitive_settings_key(str(key))
            }

        # Dateien zunächst in den Speicher lesen, bevor QSettings verändert werden.
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
            target = _safe_member_path(root, relative)
            if target is None:
                continue
            pending_files.append((target, zf.read(info)))

    settings_snapshot = settings_to_dict(settings)
    file_snapshots: dict[Path, bytes | None] = {
        target: target.read_bytes() if target.exists() and target.is_file() else None
        for target, _content in pending_files
    }

    try:
        if clear_settings:
            settings.clear()
        for key, value in settings_data.items():
            settings.setValue(str(key), _json_restore(value))
        for key, value in preserved_sensitive.items():
            settings.setValue(str(key), value)

        for target, content in pending_files:
            target.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_bytes(target, content)
            restored_files.append(str(target))

        settings.sync()
    except Exception:
        _restore_settings_snapshot(settings, settings_snapshot)
        _restore_file_snapshots(file_snapshots)
        raise
    return {
        "manifest": manifest,
        "restored_files": restored_files,
        "secret_mode": secret_mode,
        "legacy_plaintext_secrets_restored": bool(
            secret_mode == SECRET_MODE_LEGACY_PLAINTEXT
            and restore_legacy_plaintext_secrets
        ),
    }


def _restore_settings_snapshot(settings, snapshot: dict[str, Any]) -> None:
    try:
        settings.clear()
        for key, value in snapshot.items():
            settings.setValue(str(key), _json_restore(value))
        settings.sync()
    except Exception:
        # Der ursprüngliche Fehler wird erneut geworfen; dieser Versuch ist Best Effort.
        _LOG.exception("QSettings-Rollback nach fehlgeschlagenem Restore ist fehlgeschlagen.")


def _restore_file_snapshots(snapshots: dict[Path, bytes | None]) -> None:
    for target, content in snapshots.items():
        try:
            if content is None:
                if target.exists() and target.is_file():
                    target.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_bytes(target, content)
        except Exception:
            # Der eigentliche Restore-Fehler bleibt führend.
            _LOG.exception("Datei-Rollback nach fehlgeschlagenem Restore ist fehlgeschlagen: %s", target)


def _atomic_write_bytes(path: Path, content: bytes) -> None:
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
