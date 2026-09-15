# -*- coding: utf-8 -*-
"""Transactional conflict handling for generated Jellyfin NFO files."""
from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True, slots=True)
class NfoTargetPlan:
    target: Path
    status: str
    should_write: bool
    conflict_mode: str


def plan_nfo_target(target: Path, conflict_mode: str) -> NfoTargetPlan:
    mode = str(conflict_mode or "skip").strip().lower()
    if not target.exists():
        return NfoTargetPlan(target, "created", True, mode)
    if mode == "skip":
        return NfoTargetPlan(target, "skipped", False, mode)
    if mode == "backup":
        return NfoTargetPlan(target, "backed_up", True, mode)
    return NfoTargetPlan(target, "replaced", True, "overwrite")


def commit_nfo(plan: NfoTargetPlan, writer: Callable[[Path], object]) -> tuple[Path, Path | None]:
    """Write safely and return ``(target, backup_path)``.

    overwrite: the atomic writer replaces the old target only after a complete
    temp write. backup: first build a complete pending NFO, durably *copy* the
    old NFO to its backup path and only then atomically replace the live NFO.
    The live target therefore never disappears between two rename operations.
    """
    target = plan.target
    if not plan.should_write:
        return target, None
    if plan.conflict_mode != "backup" or not target.exists():
        writer(target)
        return target, None

    pending = target.with_name(f".{target.name}.__pending__{uuid.uuid4().hex}.tmp")
    backup = unique_nfo_backup_path(target)
    writer(pending)
    try:
        _durable_backup_copy(target, backup)
        try:
            os.replace(str(pending), str(target))
            _fsync_directory(target.parent)
        except Exception:
            # Normal, catchable install failures are a transaction rollback:
            # the live target was never removed, so the just-created backup is
            # not needed and must not look like a successful backup operation.
            try:
                backup.unlink(missing_ok=True)
                _fsync_directory(backup.parent)
            except OSError:
                pass
            raise
    finally:
        try:
            pending.unlink(missing_ok=True)
        except OSError:
            pass
    return target, backup


def _durable_backup_copy(source: Path, backup: Path) -> None:
    """Create a durable backup without ever removing ``source``.

    Copy into a same-directory staging file, fsync the bytes, then atomically
    publish the backup.  A power loss can leave an extra staging file, but the
    live NFO and any previously published backup remain valid.
    """
    staging = backup.with_name(f".{backup.name}.__copy__{uuid.uuid4().hex}.tmp")
    try:
        with source.open("rb") as src, staging.open("xb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        try:
            shutil.copystat(source, staging, follow_symlinks=True)
        except OSError:
            pass
        os.replace(str(staging), str(backup))
        _fsync_directory(backup.parent)
    finally:
        try:
            staging.unlink(missing_ok=True)
        except OSError:
            pass


def _fsync_directory(directory: Path) -> None:
    """Best-effort directory fsync; unavailable on some Windows filesystems."""
    flags = getattr(os, "O_RDONLY", 0)
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    fd = None
    try:
        fd = os.open(str(directory), flags | directory_flag)
        os.fsync(fd)
    except (AttributeError, OSError):
        return
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


def unique_nfo_backup_path(target: Path) -> Path:
    return _unique_path(target.with_suffix(target.suffix + ".bak"))


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    for idx in range(1, 1000):
        candidate = parent / f"{stem}_{idx:02d}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Kein freier Dateiname gefunden: {path.name}")
