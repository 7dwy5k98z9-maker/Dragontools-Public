# -*- coding: utf-8 -*-
"""Hinweis- und Texthelfer fuer Film-Preflight-Zeilen."""
from __future__ import annotations

from PyQt6.QtWidgets import QLabel, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from .preflight_widget_common import _fmt_path


def add_release_warning(layout: QVBoxLayout, release_warnings: tuple[str, ...]) -> None:
    if not release_warnings:
        return
    warning = QLabel(
        "  ⚠️ Nicht normalisierter/Release-Dateiname erkannt: "
        + "; ".join(release_warnings)
        + ". Die Online-Metadatensuche wird automatisch gestartet."
    )
    warning.setWordWrap(True)
    warning.setStyleSheet("color:#b45309; font-size:11px;")
    layout.addWidget(warning)


def hidden_edit_row(label: str, edit: QLineEdit, callback, placeholder: str = "") -> QWidget:
    if placeholder:
        edit.setPlaceholderText(placeholder)
    edit.textChanged.connect(callback)
    row = QHBoxLayout()
    row.addWidget(QLabel(label))
    row.addWidget(edit, 1)
    widget = QWidget()
    widget.setLayout(row)
    widget.setVisible(False)
    return widget


def provider_label(suggestion) -> str:
    provider = str(getattr(suggestion, "provider", "") or "").casefold()
    return "TheTVDB" if provider == "thetvdb" else "TMDB"


def metadata_lookup_started_text() -> str:
    return "  🌐 Suche: Mediathek und Online-Filmdaten werden im Hintergrund geprüft …"


def metadata_lookup_failed_text(message: str = "") -> str:
    detail = f" – {message}" if message else ""
    return f"  🌐 Online-Metadaten: Film-Metadaten konnten nicht geladen werden{detail}"


def metadata_movie_suggestion_text(suggestion) -> str:
    provider = provider_label(suggestion)
    if not suggestion.has_collection:
        return f"  🌐 Zielquelle: {provider} – Einzelfilm erkannt"
    part_info = f", {suggestion.collection_part_count} Teile" if suggestion.collection_part_count else ""
    return f"  🌐 Zielquelle: {provider} – Filmreihe erkannt: {suggestion.collection_name}{part_info}"


def existing_movie_hint(movie_dir: str, source: str = "database", notice: str = "") -> str:
    is_db = str(source or "").casefold() == "database"
    source_text = "🗄 Zielquelle: Mediathek-Datenbank" if is_db else "📁 Zielquelle: Ordnersuche"
    note = f"\n  ℹ️ {notice}" if str(notice or "").strip() else ""
    return f"  {source_text} – {_fmt_path(movie_dir)}{note}"
