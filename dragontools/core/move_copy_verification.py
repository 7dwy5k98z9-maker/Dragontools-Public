# -*- coding: utf-8 -*-
"""Cheap post-copy integrity checks for destructive cross-volume moves."""
from __future__ import annotations

from pathlib import Path

_SAMPLE_BYTES = 1024 * 1024


def _read_sample(path: Path, offset: int, length: int) -> bytes:
    with path.open("rb") as handle:
        handle.seek(offset)
        return handle.read(length)


def verify_staged_file_copy(source: str | Path, staged: str | Path) -> None:
    """Verify size and representative byte ranges before the source is deleted.

    A full second read of multi-gigabyte media would double move I/O.  DragonTools
    therefore compares the complete content for small files and first/middle/last
    1 MiB for larger files.  Any mismatch aborts the transaction before commit.
    """
    src = Path(source)
    dst = Path(staged)
    source_size = src.stat().st_size
    staged_size = dst.stat().st_size
    if staged_size != source_size:
        raise OSError(
            f"Größenprüfung fehlgeschlagen: Quelle={source_size} Byte, Kopie={staged_size} Byte"
        )
    if source_size == 0:
        return

    if source_size <= _SAMPLE_BYTES * 3:
        offsets = (0,)
        sample_size = source_size
    else:
        sample_size = _SAMPLE_BYTES
        offsets = (
            0,
            max(0, (source_size // 2) - (sample_size // 2)),
            max(0, source_size - sample_size),
        )

    for offset in dict.fromkeys(offsets):
        length = min(sample_size, source_size - offset)
        if _read_sample(src, offset, length) != _read_sample(dst, offset, length):
            raise OSError(
                "Integritätsprüfung der Kopie fehlgeschlagen "
                f"(Abweichung bei Byte-Offset {offset})."
            )
