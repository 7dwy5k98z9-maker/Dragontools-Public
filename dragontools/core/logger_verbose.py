# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from .settings import (
    SET_KEY_LOG_ROOT, SET_KEY_VERBOSE_LOG_ENABLED, SET_KEY_VERBOSE_LOG_ROOT,
    app_qsettings, settings_bool, settings_text,
)

_VERBOSE_MAX_FILES = 10

def make_verbose_log_dir(base_root: str | Path) -> Path:
    """Erstellt und gibt zurück: <base_root>/VerboseLog/
    Keine Jahres-/Monatsunterordner. Direkt .txt-Dateien.
    """
    p = Path(base_root) / "VerboseLog"
    p.mkdir(parents=True, exist_ok=True)
    return p


def verbose_log_dir_from_settings(settings=None) -> Path:
    """Liest den Verbose-Log-Pfad aus QSettings."""
    try:
        s = settings or app_qsettings()
        root = settings_text(s, SET_KEY_VERBOSE_LOG_ROOT, "")
        if root:
            return make_verbose_log_dir(root)
        # Fallback: gleicher Basis-Ordner wie normaler Log
        normal_root = settings_text(s, SET_KEY_LOG_ROOT, "")
        if normal_root:
            return make_verbose_log_dir(normal_root)
    except Exception:
        pass
    return make_verbose_log_dir(Path.home() / "Documents" / "DragonTools")


def _cleanup_verbose_dir(log_dir: Path) -> None:
    """Löscht älteste .txt-Dateien wenn mehr als _VERBOSE_MAX_FILES vorhanden."""
    try:
        txts = sorted(log_dir.glob("*.txt"), key=lambda p: p.stat().st_mtime)
        while len(txts) >= _VERBOSE_MAX_FILES:
            txts.pop(0).unlink(missing_ok=True)
    except Exception:
        pass


class VerboseLogger:
    """Separater Logger für Debug-/Trace-Meldungen.

    Schreibt in eigenen Ordner (keine Jahres-/Monatsunterordner).
    Max. 10 .txt-Dateien, älteste wird automatisch gelöscht.
    Logt NICHT in die GUI – nur in die Datei.
    Wirft keine Exceptions: Konvertierung läuft auch ohne verbose Log.
    """

    def __init__(self, log_dir: Path | None = None, enabled: bool = True) -> None:
        self.enabled = enabled
        self.log_file: Path | None = None
        self.long_log_file: Path | None = None

        if not enabled:
            return

        try:
            d = log_dir or verbose_log_dir_from_settings()
            d.mkdir(parents=True, exist_ok=True)
            _cleanup_verbose_dir(d)
            ts = datetime.now().strftime("%d.%m.%Y_%H-%M-%S")
            self.log_file = d / f"verbose_{ts}.txt"
            # Datei anlegen
            self.log_file.write_text(
                f"# DragonTools VerboseLog – {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
                f"# Dieser Log enthält interne Debug-/Trace-Meldungen.\n\n",
                encoding="utf-8",
            )
        except Exception as exc:
            self.log_file = None
            print(f"[VerboseLogger] Konnte Log-Datei nicht erstellen: {exc}", file=sys.stderr)

    def write(self, msg: str) -> None:
        """Schreibt eine Zeile in den Verbose-Log. Niemals Exception."""
        if not self.enabled or not self.log_file:
            return
        try:
            ts = datetime.now().strftime("%H:%M:%S")
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {msg}\n")
        except Exception:
            pass

    def discard(self) -> bool:
        """Entfernt den Verbose-Log, wenn er fuer die Diagnose nicht benoetigt wird."""
        path = self.log_file
        self.log_file = None
        if not path:
            return False
        try:
            path.unlink(missing_ok=True)
            return True
        except Exception:
            return False

    @property
    def log_dir(self) -> Path | None:
        return self.log_file.parent if self.log_file else None


def create_verbose_logger(settings=None) -> VerboseLogger:
    """Erzeugt einen VerboseLogger aus den globalen Einstellungen."""
    try:
        s = settings or app_qsettings()
        enabled = settings_bool(s, SET_KEY_VERBOSE_LOG_ENABLED, True)
        log_dir = verbose_log_dir_from_settings(s)
        return VerboseLogger(log_dir=log_dir, enabled=bool(enabled))
    except Exception:
        return VerboseLogger(enabled=True)


def discard_verbose_after_clean_run(
    verbose_logger,
    *,
    abort_requested: bool = False,
    failed_count: int = 0,
    force_keep: bool = False,
) -> bool:
    """Entfernt den Verbose-Log nur nach einem sauberen fehlerfreien Lauf."""
    if abort_requested or force_keep or failed_count > 0:
        return False
    try:
        return bool(verbose_logger and verbose_logger.discard())
    except Exception:
        return False
