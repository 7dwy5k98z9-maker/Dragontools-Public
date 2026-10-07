# -*- coding: utf-8 -*-
"""Qt-unabhängige Verträge und Queue-Helfer für Worker.

Dieses Modul enthält bewusst nur Typen/Helfer, die kein QThread benötigen.
Dadurch können Core-Services und Queue-Logik sie importieren, ohne indirekt
PyQt6 zu laden.
"""
from __future__ import annotations

from enum import Enum

from ..core.path_syntax import path_compare_key


class RemoveFileStatus(str, Enum):
    """Gemeinsamer Statusvertrag für ``worker.remove_file()``."""

    REMOVED = "removed"
    PENDING_REMOVE = "pending_remove"
    CURRENT = "current"
    NOT_FOUND = "not_found"


def normalize_worker_path(path: str) -> str:
    """Normalisiert Dateipfade für Queue-/Override-Vergleiche."""

    return path_compare_key(path)


def file_override_for_path(mapping, input_path: str):
    """Return a per-file override using the same canonical path semantics as the queue."""
    if not mapping:
        return None
    try:
        exact = mapping.get(input_path)
    except AttributeError:
        return None
    if exact is not None:
        return exact
    wanted = normalize_worker_path(input_path)
    for raw_path, value in mapping.items():
        try:
            if normalize_worker_path(raw_path) == wanted:
                return value
        except (TypeError, ValueError, OSError):
            continue
    return None


__all__ = ["RemoveFileStatus", "normalize_worker_path", "file_override_for_path"]
