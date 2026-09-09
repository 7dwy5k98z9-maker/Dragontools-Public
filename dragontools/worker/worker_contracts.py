# -*- coding: utf-8 -*-
"""Qt-unabhängige Verträge und Queue-Helfer für Worker.

Dieses Modul enthält bewusst nur Typen/Helfer, die kein QThread benötigen.
Dadurch können Core-Services und Queue-Logik sie importieren, ohne indirekt
PyQt6 zu laden.
"""
from __future__ import annotations

from enum import Enum

from ..core.paths import path_compare_key


class RemoveFileStatus(str, Enum):
    """Gemeinsamer Statusvertrag für ``worker.remove_file()``."""

    REMOVED = "removed"
    PENDING_REMOVE = "pending_remove"
    CURRENT = "current"
    NOT_FOUND = "not_found"


def normalize_worker_path(path: str) -> str:
    """Normalisiert Dateipfade für Queue-/Override-Vergleiche."""

    return path_compare_key(path)


__all__ = ["RemoveFileStatus", "normalize_worker_path"]
