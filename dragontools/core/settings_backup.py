"""Öffentliche Fassade für DragonTools-Einstellungsbackups.

Die Implementierung ist nach Format/Serialisierung, Kryptografie, Export und
transaktionalem Restore getrennt. Bestehende Importpfade bleiben stabil.
"""
from __future__ import annotations

from .settings_backup_common import (
    BACKUP_FORMAT,
    BACKUP_FORMAT_VERSION,
    SECRET_MODE_ENCRYPTED,
    SECRET_MODE_EXCLUDED,
    SECRET_MODE_LEGACY_PLAINTEXT,
    SECRETS_ENTRY,
    BackupEncryptionUnavailable,
    BackupPasswordRequired,
    InvalidBackupPassword,
    default_backup_dir,
    default_backup_path,
    dragon_documents_dir,
    settings_to_dict,
    iter_backup_files as _iter_backup_files,
)
from .settings_backup_export import export_backup, inspect_backup
from .settings_backup_restore import restore_backup

__all__ = [
    "BACKUP_FORMAT", "BACKUP_FORMAT_VERSION", "SECRET_MODE_ENCRYPTED",
    "SECRET_MODE_EXCLUDED", "SECRET_MODE_LEGACY_PLAINTEXT", "SECRETS_ENTRY",
    "BackupEncryptionUnavailable", "BackupPasswordRequired", "InvalidBackupPassword",
    "dragon_documents_dir", "default_backup_dir", "default_backup_path",
    "settings_to_dict", "inspect_backup", "export_backup", "restore_backup",
]
