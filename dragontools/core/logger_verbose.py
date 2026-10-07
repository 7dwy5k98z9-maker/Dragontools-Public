# -*- coding: utf-8 -*-
from __future__ import annotations
import logging

import os
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path

from .settings_storage import SET_KEY_LOG_ROOT, SET_KEY_VERBOSE_LOG_ENABLED, SET_KEY_VERBOSE_LOG_ROOT
from .settings_access import app_qsettings, settings_bool, settings_text
from .diagnostic_redaction import redact_sensitive_text

_VERBOSE_MAX_FILES = 10
_VERBOSE_LOCK = threading.RLock()
_ACTIVE_VERBOSE_FILES: set[Path] = set()

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
        logging.getLogger(__name__).debug("Unterdrückte Best-Effort-Ausnahme in verbose_log_dir_from_settings.", exc_info=True)
    return make_verbose_log_dir(Path.home() / "Documents" / "DragonTools")


def _cleanup_verbose_dir(log_dir: Path) -> None:
    """Löscht älteste .txt-Dateien wenn mehr als _VERBOSE_MAX_FILES vorhanden."""
    try:
        txts = sorted(
            (p for p in log_dir.glob("*.txt") if p not in _ACTIVE_VERBOSE_FILES),
            key=lambda p: p.stat().st_mtime,
        )
        while len(txts) >= _VERBOSE_MAX_FILES:
            txts.pop(0).unlink(missing_ok=True)
    except Exception:
        logging.getLogger(__name__).debug("Unterdrückte Best-Effort-Ausnahme in _cleanup_verbose_dir.", exc_info=True)


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
            with _VERBOSE_LOCK:
                _cleanup_verbose_dir(d)
                # Several converter workers can start in the same second.
                # A second-resolution filename made those independent logger
                # instances share/delete each other's file.  Include the
                # process id and a random ownership token to make the file
                # unambiguous even under parallel starts.
                ts = datetime.now().strftime("%d.%m.%Y_%H-%M-%S_%f")
                token = uuid.uuid4().hex[:8]
                self.log_file = d / f"verbose_{ts}_p{os.getpid()}_{token}.txt"
                self.log_file.write_text(
                    f"# DragonTools VerboseLog – {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
                    f"# Dieser Log enthält interne Debug-/Trace-Meldungen.\n\n",
                    encoding="utf-8",
                )
                _ACTIVE_VERBOSE_FILES.add(self.log_file)
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
                f.write(f"[{ts}] {redact_sensitive_text(msg)}\n")
        except Exception:
            logging.getLogger(__name__).debug("Unterdrückte Best-Effort-Ausnahme in write.", exc_info=True)

    def discard(self) -> bool:
        """Entfernt den Verbose-Log, wenn er fuer die Diagnose nicht benoetigt wird."""
        path = self.log_file
        self.log_file = None
        if not path:
            return False
        try:
            with _VERBOSE_LOCK:
                _ACTIVE_VERBOSE_FILES.discard(path)
                path.unlink(missing_ok=True)
            return True
        except Exception:
            return False

    def release(self) -> None:
        """Gibt die Laufzeit-Ownership frei, behält die Diagnose-Datei aber."""
        path = self.log_file
        if not path:
            return
        with _VERBOSE_LOCK:
            _ACTIVE_VERBOSE_FILES.discard(path)

    @property
    def log_dir(self) -> Path | None:
        return self.log_file.parent if self.log_file else None


def create_verbose_logger(settings=None) -> VerboseLogger:
    """Erzeugt einen VerboseLogger aus den globalen Einstellungen."""
    try:
        s = settings or app_qsettings()
        enabled = settings_bool(s, SET_KEY_VERBOSE_LOG_ENABLED, True)
        if not enabled:
            return VerboseLogger(enabled=False)
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
        try:
            if verbose_logger and hasattr(verbose_logger, "release"):
                verbose_logger.release()
        except Exception:
            logging.getLogger(__name__).debug(
                "VerboseLogger-Ownership konnte nicht freigegeben werden.",
                exc_info=True,
            )
        return False
    try:
        return bool(verbose_logger and verbose_logger.discard())
    except Exception:
        return False
