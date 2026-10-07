# -*- coding: utf-8 -*-
"""Transactional conflict handling for generated Jellyfin NFO files."""
from __future__ import annotations

import os
import shutil
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from ..core.move_transaction import publish_staged_no_replace

_NFO_TARGET_LOCKS_GUARD = threading.Lock()
_NFO_TARGET_LOCKS: dict[str, tuple[threading.Lock, int]] = {}


class nfo_target_lock:
    """Serialize DragonTools commits to one NFO target inside this process.

    Conflict policies such as ``skip`` are a read-then-write decision.  Without
    a keyed lock, two concurrent jobs can both observe an absent target and the
    second atomic writer will replace the first one despite ``skip``.
    """

    def __init__(self, target: str | Path) -> None:
        self.key = str(Path(target).resolve()).casefold()
        self._lock: threading.Lock | None = None

    def __enter__(self):
        with _NFO_TARGET_LOCKS_GUARD:
            lock, refs = _NFO_TARGET_LOCKS.get(self.key, (threading.Lock(), 0))
            _NFO_TARGET_LOCKS[self.key] = (lock, refs + 1)
            self._lock = lock
        self._lock.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        lock = self._lock
        if lock is None:
            return
        lock.release()
        with _NFO_TARGET_LOCKS_GUARD:
            current = _NFO_TARGET_LOCKS.get(self.key)
            if current is not None and current[0] is lock:
                refs = current[1] - 1
                if refs <= 0:
                    _NFO_TARGET_LOCKS.pop(self.key, None)
                else:
                    _NFO_TARGET_LOCKS[self.key] = (lock, refs)
        self._lock = None


def reset_nfo_target_locks_for_tests() -> None:
    with _NFO_TARGET_LOCKS_GUARD:
        _NFO_TARGET_LOCKS.clear()


@dataclass(frozen=True, slots=True)
class NfoTargetPlan:
    target: Path
    status: str
    should_write: bool
    conflict_mode: str


def plan_nfo_target(target: Path, conflict_mode: str) -> NfoTargetPlan:
    mode = str(conflict_mode or "skip").strip().lower()
    if mode not in {'skip','overwrite','backup'}:
        mode = 'skip'
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
    if plan.conflict_mode not in {'backup', 'skip'}:
        writer(target)
        return target, None

    pending = target.with_name(f".{target.name}.__pending__{uuid.uuid4().hex}.tmp")
    backup = unique_nfo_backup_path(target)
    try:
        writer(pending)
        if plan.conflict_mode == 'skip':
            publish_staged_no_replace(pending, target)
            _fsync_directory(target.parent)
            return target, None
        if not target.exists():
            publish_staged_no_replace(pending, target)
            _fsync_directory(target.parent)
            return target, None
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


def commit_prepared_nfo(plan: NfoTargetPlan, prepared_path: str | Path) -> tuple[Path, Path | None]:
    """Install a fully rendered staging NFO using the normal conflict policy.

    The source NFO may live in the converter's staging directory.  Installation
    remains atomic for overwrite mode and keeps the existing transaction rules
    for backup mode.
    """
    prepared = Path(prepared_path)
    if not prepared.exists():
        raise FileNotFoundError(f"Vorbereitete NFO fehlt: {prepared}")

    def _writer(target: Path) -> None:
        _atomic_copy(prepared, target)

    return commit_nfo(plan, _writer)


def _atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(f".{target.name}.__prepared__{uuid.uuid4().hex}.tmp")
    try:
        with source.open("rb") as src, staging.open("xb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        os.replace(str(staging), str(target))
        _fsync_directory(target.parent)
    finally:
        try:
            staging.unlink(missing_ok=True)
        except OSError:
            pass


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
        publish_staged_no_replace(staging, backup)
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
