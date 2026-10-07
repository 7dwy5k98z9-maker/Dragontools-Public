# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import shutil
from pathlib import Path

from .path_syntax import is_windows_style_path, normalize_user_path, to_long_path


def _resolved(path_like) -> Path:
    raw = os.fspath(path_like)
    # Destructive helpers must only operate on paths interpreted by the local
    # filesystem.  Treating a foreign Windows path as a relative POSIX name
    # (or vice versa) would make the containment check meaningless.
    if os.name != "nt" and is_windows_style_path(raw):
        raise ValueError("Windows-Pfad auf Nicht-Windows-Host")
    return Path(normalize_user_path(raw)).resolve(strict=False)


def _unresolved_local(path_like) -> Path:
    raw = os.fspath(path_like)
    if os.name != "nt" and is_windows_style_path(raw):
        raise ValueError("Windows-Pfad auf Nicht-Windows-Host")
    # Do not use normalize_user_path() here on POSIX: it intentionally calls
    # Path.resolve(), which would dereference the very symlink we need to
    # reject before a destructive operation.
    if os.name != "nt":
        return Path(os.path.abspath(os.path.normpath(os.path.expanduser(raw))))
    return Path(normalize_user_path(raw))


def _is_link_or_junction(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        return bool(callable(is_junction) and is_junction())
    except OSError:
        # Destructive operations fail closed if the link/reparse status cannot
        # be established reliably.
        return True


def _is_root(path: Path) -> bool:
    return path == Path(path.anchor)


def _has_link_ancestor(base_dir, target_path) -> bool:
    try:
        base = _unresolved_local(base_dir)
        target = _unresolved_local(target_path)
        target.relative_to(base)
        for entry in (target, *target.parents):
            if _is_link_or_junction(entry):
                return True
            if entry == base:
                return False
    except (OSError, ValueError, TypeError):
        return True
    return True


def is_safe_subpath(base_dir, target_path) -> bool:
    try:
        base = _resolved(base_dir)
        target = _resolved(target_path)
    except Exception:
        return False

    if not base.exists():
        return False
    if _is_root(base) or _is_root(target):
        return False
    # Destructive helpers are defined for descendants, never the ownership
    # root itself.  Accepting base == target would allow safe_rmtree(base, base)
    # to delete the complete managed tree after a malformed/empty relative path.
    if target == base:
        return False

    try:
        target.relative_to(base)
    except ValueError:
        return False
    return True


def safe_unlink(base_dir, target_path) -> bool:
    if not is_safe_subpath(base_dir, target_path):
        return False

    try:
        unresolved = _unresolved_local(target_path)
    except Exception:
        return False
    if _has_link_ancestor(base_dir, unresolved):
        return False

    target = _resolved(target_path)
    if target.is_dir():
        return False

    try:
        Path(to_long_path(target)).unlink(missing_ok=True)
    except Exception:
        return False
    return True


def safe_rmtree(base_dir, target_path) -> bool:
    if not is_safe_subpath(base_dir, target_path):
        return False

    try:
        unresolved = _unresolved_local(target_path)
    except Exception:
        return False
    if _has_link_ancestor(base_dir, unresolved):
        return False

    target = _resolved(target_path)
    if not target.exists() or not target.is_dir() or _is_root(target):
        return False

    try:
        shutil.rmtree(to_long_path(target))
    except Exception:
        return False
    return True
