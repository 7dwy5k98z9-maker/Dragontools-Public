# -*- coding: utf-8 -*-
"""DragonTools logging facade and core writer implementation."""
from __future__ import annotations

import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable

from .logger_messages import DragonLoggerMessageMixin
from .logger_paths import (
    _fd, _fs, _ts, log_base_from_settings, log_settings_from_qsettings,
    make_log_dir, resolve_log_month_dir,
)
from .logger_verbose import (
    VerboseLogger, create_verbose_logger, discard_verbose_after_clean_run,
    make_verbose_log_dir, verbose_log_dir_from_settings,
)

def create_worker_logger(
    *,
    gui_callback: Callable[[str], None] | None = None,
    settings=None,
    log_file_path: str | Path | None = None,
) -> "DragonLogger":
    """Erzeugt Worker-Logger aus der globalen Logging-Konfiguration."""
    enabled, base_root = log_settings_from_qsettings(settings)
    log_dir = Path(log_file_path).parent if log_file_path else (
        make_log_dir(base_root) if enabled else Path(base_root) / "Logging"
    )
    return DragonLogger(log_dir, log_enabled=enabled, gui_callback=gui_callback)


class DragonLogger(DragonLoggerMessageMixin):
    """Thread-safe log writer; message formatting lives in a dedicated mixin."""

    def __init__(
        self,
        log_dir: str | Path,
        log_enabled: bool = True,
        gui_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.log_enabled = log_enabled
        self.log_dir = Path(log_dir)
        self.gui_callback = gui_callback
        self.log_file: Path | None = None

        # Diagnose-Zähler für stille Ausfälle. Ohne diese Zähler konnte ein
        # kaputter Log-Pfad (volle Platte, kein Schreibrecht, GUI-Callback
        # wirft) komplett lautlos bleiben. Beim ersten Fehler melden wir auf
        # stderr und setzen das Flag, alle weiteren werden nur noch gezählt.
        # Am Lauf-Ende werden die Gesamtzahlen via failure_summary exponiert,
        # damit der Aufrufer (z.B. summary()) sie dem Nutzer zeigen kann.
        self._file_write_failures: int = 0
        self._gui_callback_failures: int = 0
        self._file_failure_reported: bool = False
        self._gui_failure_reported: bool = False
        self._write_lock = threading.Lock()

        if self.log_enabled:
            try:
                self.log_dir.mkdir(parents=True, exist_ok=True)
                ts = datetime.now().strftime("%d.%m.%Y_%H-%M")
                self.log_file = self.log_dir / f"{ts}.txt"
                self.long_log_file = self.log_dir / f"{ts}_lang.txt"
            except Exception as exc:
                # mkdir selbst kann scheitern (z.B. UNC-Pfad offline).
                # Keine Exception durchreichen - Logging darf die App nicht
                # kippen - aber sichtbar auf stderr melden, damit der
                # fehlende Log nicht schweigend untergeht.
                self.log_file = None
                print(
                    f"[DragonLogger] Log-Verzeichnis konnte nicht erstellt "
                    f"werden ({self.log_dir}): {exc}",
                    file=sys.stderr,
                )

    def set_gui_callback(self, cb: Callable[[str], None]) -> None:
        self.gui_callback = cb

    @property
    def has_logging_failures(self) -> bool:
        """True wenn seit dem letzten drain_failures() Log-Fehler aufgetreten sind."""
        return self._file_write_failures > 0 or self._gui_callback_failures > 0

    @property
    def failure_summary(self) -> str | None:
        """Menschenlesbare Zusammenfassung aller Log-Fehler, oder None wenn keine.

        Wird von summary() automatisch in die Log-Datei und GUI geschrieben.
        Kann auch extern abgefragt werden (z.B. für einen Abschluss-Dialog).
        """
        parts: list[str] = []
        if self._file_write_failures > 0:
            parts.append(
                f"{self._file_write_failures} Log-Schreibfehler (Datei: '{self.log_file}')"
            )
        if self._gui_callback_failures > 0:
            parts.append(
                f"{self._gui_callback_failures} GUI-Callback-Fehler"
            )
        if not parts:
            return None
        return "⚠️  Log-Infrastruktur: " + " | ".join(parts) + " – Einträge wurden möglicherweise verworfen."

    def drain_failures(self) -> tuple[int, int]:
        """Gibt (file_failures, gui_failures) zurück und setzt die Zähler zurück.

        Nützlich für Tests und für Worker-Runs, die einen neuen Log-Abschnitt
        beginnen und saubere Zähler brauchen.
        """
        f, g = self._file_write_failures, self._gui_callback_failures
        self._file_write_failures = 0
        self._gui_callback_failures = 0
        self._file_failure_reported = False
        self._gui_failure_reported = False
        return f, g

    def _write(self, line: str, to_gui: bool = False, to_short: bool = False) -> None:
        # Vollständiger bisheriger Log -> *_lang.txt. Der sichtbare Standardlog
        # bekommt nur explizit markierte, kompakte Kernmeldungen.
        long_target = self.long_log_file or self.log_file
        if long_target:
            try:
                with self._write_lock:
                    with open(long_target, "a", encoding="utf-8") as f:
                        f.write(line + "\n")
            except Exception as exc:
                # Logging darf nie eine Exception weitergeben, aber
                # stillschweigendes Schlucken hat in der Vergangenheit
                # dazu geführt, dass Ausfaelle des Log-Pfads gar nicht
                # bemerkt wurden. Ersten Fehler einmal sichtbar melden,
                # dann nur noch zaehlen.
                self._file_write_failures += 1
                if not self._file_failure_reported:
                    self._file_failure_reported = True
                    print(
                        f"[DragonLogger] Schreibfehler in Log-Datei "
                        f"'{self.log_file}': {exc}",
                        file=sys.stderr,
                    )
                    traceback.print_exc(file=sys.stderr)
        if to_short and self.log_file:
            try:
                with self._write_lock:
                    with open(self.log_file, "a", encoding="utf-8") as f:
                        f.write(line + "\n")
            except Exception as exc:
                self._file_write_failures += 1
                if not self._file_failure_reported:
                    self._file_failure_reported = True
                    print(f"[DragonLogger] Schreibfehler in Kurzlog '{self.log_file}': {exc}", file=sys.stderr)
        if to_gui and self.gui_callback:
            try:
                self.gui_callback(line)
            except Exception as exc:
                self._gui_callback_failures += 1
                if not self._gui_failure_reported:
                    self._gui_failure_reported = True
                    print(
                        f"[DragonLogger] GUI-Callback hat eine Exception "
                        f"geworfen: {exc}",
                        file=sys.stderr,
                    )
                    traceback.print_exc(file=sys.stderr)

    def info(self, msg: str) -> None:
        text = str(msg)
        compact = text.lstrip()
        short = text.startswith(("Quelle:", "Ziel:", "Ergebnis:")) or compact.startswith(
            ("📄 Exportiere ", "📄 Sidecar OK:")
        )
        self._write(f"ℹ️  {msg}", to_gui=short, to_short=short)

    def info_short(self, msg: str) -> None:
        """Kompakte INFO, die bewusst im sichtbaren Kurzlog erscheint."""
        self._write(f"ℹ️  {msg}", to_gui=True, to_short=True)

    def warn(self, msg: str) -> None:
        self._write(f"⚠️  {msg}", to_gui=True, to_short=True)

    def error(self, msg: str) -> None:
        self._write(f"❌  {msg}", to_gui=True, to_short=True)

    def success(self, msg: str) -> None:
        self._write(f"✅  {msg}", to_gui=True, to_short=True)

    def decision(self, msg: str) -> None:
        text = str(msg)
        short = text.startswith(("Sub #", "Keine kompatiblen Untertitel", "MP4-Ziel:"))
        self._write(f"  → {text}", to_gui=short, to_short=short)

    def separator(self) -> None:
        self._write("-" * 60, to_gui=False)

__all__ = [
    "DragonLogger", "VerboseLogger", "create_worker_logger", "create_verbose_logger",
    "discard_verbose_after_clean_run", "make_log_dir", "resolve_log_month_dir",
    "log_base_from_settings", "log_settings_from_qsettings",
    "make_verbose_log_dir", "verbose_log_dir_from_settings",
]
