# -*- coding: utf-8 -*-
"""Persistente Diagnoseberichte für GUI-Initialisierungsfehler."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .logger_paths import log_base_from_settings, make_log_dir
from .version import APP_VERSION


def write_tab_load_error_report(
    *,
    tab_key: str,
    tab_label: str,
    error: BaseException,
    traceback_text: str,
    settings: Any = None,
    log_root: str | Path | None = None,
) -> str:
    """Schreibt einen vollständigen Bericht für einen fehlgeschlagenen Lazy-Tab.

    GUI-Initialisierungsfehler passieren häufig bevor ein Worker-Logger existiert.
    Deshalb bekommt dieser Fehlerpfad einen eigenen persistenten Diagnosebericht
    im normalen Dragon-Tools-Loggingbaum. Der Bericht darf selbst keine
    Qt-Abhängigkeit besitzen, damit er auch headless testbar bleibt.
    """
    base_root = Path(log_root) if log_root is not None else log_base_from_settings(settings)
    report_dir = make_log_dir(base_root) / "ErrorReports" / "GUI"
    report_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    safe_key = _safe_component(tab_key) or "unknown_tab"
    report_path = report_dir / f"{now.strftime('%Y%m%d_%H%M%S_%f')}_{safe_key}_tab_load_error.txt"

    error_type = type(error).__name__
    error_message = str(error) or "-"
    trace = str(traceback_text or "").strip() or "-"
    text = "\n".join(
        [
            "Dragon Tools GUI-Fehlerbericht",
            "=" * 80,
            f"Version: {APP_VERSION}",
            f"Zeitpunkt: {now.strftime('%d.%m.%Y %H:%M:%S')}",
            f"Tab-Key: {tab_key or '-'}",
            f"Tab-Name: {tab_label or '-'}",
            f"Fehlertyp: {error_type}",
            f"Fehler: {error_message}",
            "",
            "Traceback",
            "---------",
            trace,
            "",
        ]
    )
    report_path.write_text(text, encoding="utf-8")
    return str(report_path)


def _safe_component(value: str) -> str:
    text = str(value or "").strip()
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in text).strip("._")


__all__ = ["write_tab_load_error_report"]
