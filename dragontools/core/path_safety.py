# -*- coding: utf-8 -*-
from __future__ import annotations

import shutil
from pathlib import Path

from .paths import normalize_user_path, to_long_path


def _resolved(path_like) -> Path:
    return Path(normalize_user_path(path_like))


def _is_root(path: Path) -> bool:
    return path == Path(path.anchor)


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

    try:
        target.relative_to(base)
    except ValueError:
        return False
    return True


def safe_unlink(base_dir, target_path) -> bool:
    if not is_safe_subpath(base_dir, target_path):
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

    target = _resolved(target_path)
    if not target.exists() or not target.is_dir() or _is_root(target):
        return False

    try:
        shutil.rmtree(to_long_path(target))
    except Exception:
        return False
    return True
