# -*- coding: utf-8 -*-
from __future__ import annotations

MOVE_JOURNAL_VERSION = 1
ACTIVE_MOVE_JOURNAL_NAME = "active_move.json"
JOURNAL_FILE_PREFIX = "move_"
ARCHIVE_DIR_NAME = "Abgeschlossen"
TERMINAL_OK = {"ok", "skipped"}
RETRYABLE = {"queued", "running", "error", "warn", "unknown", ""}
CLOSED_MOVE_STATUSES = {"completed"}

class MoveJournalWriteError(OSError):
    """Persistieren des Move-Journals ist fehlgeschlagen.

    Dieser Fehler ist absichtlich fatal fuer einen laufenden Move. Sobald eine
    destruktive Transaktion gestartet wurde, darf DragonTools nicht weiterarbeiten,
    wenn der Recovery-Zustand nicht dauerhaft gespeichert werden kann.
    """
