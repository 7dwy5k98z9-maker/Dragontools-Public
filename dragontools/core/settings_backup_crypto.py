from __future__ import annotations

import base64
import json
import os
from typing import Any

from .settings_backup_common import (
    BackupEncryptionUnavailable,
    BackupPasswordRequired,
    InvalidBackupPassword,
)

_AAD = b"DragonToolsBackup:secrets:v1"


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


def encrypt_sensitive_settings(data: dict[str, Any], password: str) -> bytes:
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


def decrypt_sensitive_settings(payload_bytes: bytes, password: str | None) -> dict[str, Any]:
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
