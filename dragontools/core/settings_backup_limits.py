from __future__ import annotations

from pathlib import Path
import zipfile

# DragonTools backups contain only settings plus small JSON rule/profile files.
# Limits are deliberately generous for legitimate backups while preventing a
# malformed archive from forcing unbounded memory/CPU use during restore.
MAX_BACKUP_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_BACKUP_MEMBERS = 256
MAX_BACKUP_TOTAL_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_BACKUP_MEMBER_BYTES = 64 * 1024 * 1024
MAX_BACKUP_METADATA_BYTES = 16 * 1024 * 1024
MAX_BACKUP_SECRET_ENTRY_BYTES = 16 * 1024 * 1024
COMPRESSION_RATIO_CHECK_MIN_BYTES = 1 * 1024 * 1024
MAX_BACKUP_COMPRESSION_RATIO = 200.0

_ALLOWED_COMPRESSION_TYPES = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})


class BackupArchiveLimitError(ValueError):
    """Backup überschreitet die für DragonTools zulässigen Sicherheitsgrenzen."""


def validate_backup_path_size(path: Path) -> None:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ValueError(f"Backup-Datei konnte nicht gelesen werden: {exc}") from exc
    if size > MAX_BACKUP_ARCHIVE_BYTES:
        raise BackupArchiveLimitError(
            f"Backup-Datei ist zu groß ({size} Bytes; erlaubt sind maximal {MAX_BACKUP_ARCHIVE_BYTES} Bytes)."
        )


def validate_backup_archive(zf: zipfile.ZipFile) -> None:
    infos = zf.infolist()
    if len(infos) > MAX_BACKUP_MEMBERS:
        raise BackupArchiveLimitError(
            f"Backup enthält zu viele ZIP-Einträge ({len(infos)}; erlaubt sind maximal {MAX_BACKUP_MEMBERS})."
        )

    seen_names: set[str] = set()
    total_uncompressed = 0
    for info in infos:
        normalized_name = info.filename.replace("\\", "/").casefold()
        if normalized_name in seen_names:
            raise BackupArchiveLimitError(f"Backup enthält einen doppelten ZIP-Eintrag: {info.filename}")
        seen_names.add(normalized_name)

        if info.flag_bits & 0x1:
            raise BackupArchiveLimitError(f"ZIP-verschlüsselte Backup-Einträge werden nicht unterstützt: {info.filename}")
        if info.compress_type not in _ALLOWED_COMPRESSION_TYPES:
            raise BackupArchiveLimitError(
                f"Nicht unterstützte ZIP-Kompression im Backup: {info.filename} (Typ {info.compress_type})."
            )
        if info.file_size < 0 or info.compress_size < 0:
            raise BackupArchiveLimitError(f"Ungültige Größenangabe im Backup: {info.filename}")
        if info.file_size > MAX_BACKUP_MEMBER_BYTES:
            raise BackupArchiveLimitError(
                f"Backup-Eintrag ist zu groß: {info.filename} ({info.file_size} Bytes)."
            )

        total_uncompressed += info.file_size
        if total_uncompressed > MAX_BACKUP_TOTAL_UNCOMPRESSED_BYTES:
            raise BackupArchiveLimitError(
                "Backup überschreitet die maximal zulässige entpackte Gesamtgröße."
            )

        if info.file_size >= COMPRESSION_RATIO_CHECK_MIN_BYTES:
            if info.compress_size <= 0:
                raise BackupArchiveLimitError(f"Unplausible ZIP-Kompressionsgröße: {info.filename}")
            ratio = info.file_size / info.compress_size
            if ratio > MAX_BACKUP_COMPRESSION_RATIO:
                raise BackupArchiveLimitError(
                    f"Verdächtiges ZIP-Kompressionsverhältnis bei {info.filename}: {ratio:.1f}:1."
                )


def read_backup_entry(zf: zipfile.ZipFile, name: str, *, max_bytes: int) -> bytes:
    try:
        info = zf.getinfo(name)
    except KeyError:
        raise
    if info.file_size > max_bytes:
        raise BackupArchiveLimitError(
            f"Backup-Eintrag {name} ist zu groß ({info.file_size} Bytes; maximal {max_bytes})."
        )
    return zf.read(info)
