# -*- coding: utf-8 -*-
"""Bounded-memory full-content checks for destructive cross-volume moves."""
from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass
import hashlib
import os
from .transaction_identity import stat_identity

_SAMPLE_BYTES = 1024 * 1024


@dataclass(frozen=True)
class VerifiedFileCopy:
    source_receipt: dict
    staged_receipt: dict


def verify_staged_path_copy(source: Path, staged: Path) -> None:
    """Verify directory contents and symlink targets without following links."""
    if source.is_symlink():
        if not staged.is_symlink() or os.readlink(source) != os.readlink(staged):
            raise OSError(f"Symlink-Kopie stimmt nicht überein: {source}")
    elif source.is_dir():
        if staged.is_symlink() or not staged.is_dir():
            raise OSError(f"Ordner-Kopie fehlt: {staged}")
        originals = {p.name: p for p in source.iterdir()}
        copies = {p.name: p for p in staged.iterdir()}
        if originals.keys() != copies.keys():
            raise OSError(f"Ordner-Kopie ist unvollständig: {staged}")
        for name, path in originals.items():
            verify_staged_path_copy(path, copies[name])
    else:
        if staged.is_symlink():
            raise OSError(f"Unerwarteter Symlink in Kopie: {staged}")
        verify_staged_file_copy(source, staged)


def verify_staged_file_copy(source: str | Path, staged: str | Path) -> VerifiedFileCopy | None:
    """Compare every byte before source deletion, with bounded memory."""
    src = Path(source)
    dst = Path(staged)
    source_before = stat_identity(src)
    staged_before = stat_identity(dst)
    source_size = source_before[2]
    staged_size = dst.stat().st_size
    if staged_size != source_size:
        raise OSError(
            f"Größenprüfung fehlgeschlagen: Quelle={source_size} Byte, Kopie={staged_size} Byte"
        )
    offset = 0
    digest = hashlib.sha256(b'file\0')
    with src.open('rb') as left, dst.open('rb') as right:
        while True:
            chunk = left.read(_SAMPLE_BYTES)
            if chunk != right.read(_SAMPLE_BYTES):
                raise OSError(f"Integritätsprüfung der Kopie fehlgeschlagen (Byte-Offset {offset}).")
            if not chunk:
                break
            digest.update(chunk)
            offset += len(chunk)
    if (offset != source_size or stat_identity(src) != source_before
            or stat_identity(dst) != staged_before):
        raise OSError("Quelle wurde während der Integritätsprüfung verändert.")
    if src.is_symlink() or dst.is_symlink():
        return None
    content = digest.hexdigest()
    return VerifiedFileCopy(
        {'identity': source_before, 'content': content},
        {'identity': staged_before, 'content': content},
    )
