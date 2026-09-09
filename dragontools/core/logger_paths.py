# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .settings import LOG_ENABLED_KEYS, LOG_ROOT_KEYS, app_qsettings, settings_bool, settings_text

_DE_MONTHS: dict[int, str] = {
    1: "Januar", 2: "Februar", 3: "März", 4: "April", 5: "Mai", 6: "Juni",
    7: "Juli", 8: "August", 9: "September", 10: "Oktober", 11: "November", 12: "Dezember",
}

def make_log_dir(base_root: str | Path) -> Path:
    """Erstellt und gibt zurück: <base_root>/Logging/<YYYY>/<MM-Monat>/

    Keine locale-Abhängigkeit: Monatsnamen kommen aus _DE_MONTHS.
    Wird von allen Workern genutzt – einheitliche Pfadstruktur.
    """
    now = datetime.now()
    p = Path(base_root) / "Logging" / str(now.year) / f"{now.month:02d}-{_DE_MONTHS[now.month]}"
    p.mkdir(parents=True, exist_ok=True)
    return p


def log_base_from_settings(settings=None) -> Path:
    """Liest den konfigurierten Logging-Basisordner aus QSettings."""
    try:
        s = settings or app_qsettings()
        for key in LOG_ROOT_KEYS:
            root = settings_text(s, key, "")
            if root:
                return Path(root)
    except Exception:
        pass
    return Path.home() / "Documents" / "DragonTools"


def log_settings_from_qsettings(settings=None) -> tuple[bool, Path]:
    """Liest die globalen Logging-Einstellungen mit Legacy-Fallbacks."""
    try:
        s = settings or app_qsettings()
        enabled = True
        for key in LOG_ENABLED_KEYS:
            if s.contains(key):
                enabled = settings_bool(s, key, True)
                break
        return bool(enabled), log_base_from_settings(s)
    except Exception:
        return True, log_base_from_settings()


def resolve_log_month_dir(current_log_file: str | Path | None = None) -> Path:
    """Liefert den echten aktuellen Log-Monatsordner.

    Priorität:
      1) Parent von `current_log_file`, falls vorhanden
      2) Genau der Zielordner, den ein neuer Lauf via Logger nutzen wuerde
         (make_log_dir(log_base_from_settings()))
    """
    if current_log_file:
        candidate = Path(current_log_file).parent
        if str(candidate):
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
    return make_log_dir(log_base_from_settings())


def _ts() -> str:
    return datetime.now().strftime("%d.%m.%Y %H:%M:%S Uhr")


def _fs(b: int) -> str:
    for u in ("B", "KB", "MB", "GB", "TB"):
        if abs(b) < 1024:
            return f"{b:.2f} {u}"
        b /= 1024
    return f"{b:.2f} TB"


def _fd(s: float) -> str:
    s = int(s)
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"
