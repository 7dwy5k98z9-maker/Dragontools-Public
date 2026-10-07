"""Publish a complete library without replacing files underneath SQLite handles."""
from contextlib import closing
from pathlib import Path
import os
import sqlite3
import time


def publish_library(source: Path, target: Path, *, replace_file=os.replace, timeout_s=5.0):
    # A new destination has no old WAL. Existing destinations must be updated
    # through SQLite's atomic backup transaction, keeping live handles coherent.
    if not target.exists():
        replace_file(source, target)
        return
    deadline = time.monotonic() + timeout_s
    def progress(status, remaining, total):
        if status in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED} and time.monotonic() >= deadline:
            raise sqlite3.OperationalError("Mediathek-Ziel ist belegt; Veröffentlichung abgebrochen.")
    with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(target)) as dst:
        src.backup(dst, pages=256, progress=progress, sleep=0.05)
