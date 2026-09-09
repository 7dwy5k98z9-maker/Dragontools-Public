# -*- coding: utf-8 -*-
"""Gemeinsame, kleine Helfer der Preflight-Zielwidgets."""
from __future__ import annotations

from PyQt6.QtWidgets import QFrame

from ..rules.move_rules import move_safe_stem, sanitize_win_segment
from ..core.paths import join_user_path, path_compare_key

def _safe_stem(path: str) -> str:
    """Dateiname für die Move-Zielfindung ohne technische Codec-Suffixe."""
    return move_safe_stem(path)

def _fmt_path(p: str | None, maxlen: int = 60) -> str:
    if not p: return "—"
    s = str(p)
    return ("…" + s[-(maxlen-1):]) if len(s) > maxlen else s

def _sep() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet("color: #cbd5e1;")
    return f

def _planned_target_entry(target_dir: str, relative_subpath: str = ""):
    if not relative_subpath:
        return target_dir
    return {
        "target": target_dir,
        "subpath": relative_subpath,
    }

def _series_root_from_input(base: str | None, series_name: str, existing_dir: str | None = None) -> str | None:
    """Schnelle Serienwurzel für die GUI-Vorschau ohne Netzlaufwerk-Scan."""
    if existing_dir:
        return existing_dir
    if not base or not series_name.strip():
        return None
    return join_user_path(base, sanitize_win_segment(series_name, fallback="Unbekannt"))

def _series_season_target(series_dir: str | None, season: int | None) -> str | None:
    """Schneller Staffel-Zielpfad ohne bestehende Ordner zu durchsuchen."""
    if not series_dir or season is None:
        return None
    folder = "Specials" if int(season) == 0 else f"Staffel {int(season):02d}"
    return join_user_path(series_dir, folder)

def _base_path_key(path: str | None) -> str:
    """Normalisiert Basisordner nur fuer robuste GUI-Vergleiche."""
    return path_compare_key(path) if path else ""
