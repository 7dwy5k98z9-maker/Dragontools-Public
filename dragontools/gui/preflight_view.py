# -*- coding: utf-8 -*-
"""Reiner View-Aufbau des Preflight-Dialogs."""
from __future__ import annotations

from collections import defaultdict
from PyQt6.QtCore import QSettings, QTimer
from PyQt6.QtWidgets import (
    QVBoxLayout, QLabel, QScrollArea, QWidget, QCheckBox, QDialogButtonBox,
)
from ..core.settings import APP_ORG, APP_NAME, SET_KEY_PREFLIGHT_SAVE_REPORT
from ..core.paths import user_path_name
from ..core.movie_renamer import parse_series_release_name, release_style_warnings
from .preflight_widgets import SeriesGroupWidget, FilmWidget, _sep


def build_preflight_view(dialog, files, tv_path, anime_path, filme_path, *, series_default_type: str):
    v = QVBoxLayout(dialog)

    # Kopfzeile
    hdr = QLabel(
        "<b>Zielordner vor dem Start festlegen</b><br>"
        "<span style='color:#475569;font-size:12px;'>"
        "Gleiche Serien sind zusammengefasst – einmal einstellen "
        "gilt für alle Folgen. Danach läuft alles automatisch.</span>")
    hdr.setWordWrap(True)
    v.addWidget(hdr)
    v.addWidget(_sep())

    # Scroll
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    inner   = QWidget()
    inner_v = QVBoxLayout(inner)
    inner_v.setSpacing(6)

    # ── Dateien analysieren und gruppieren ────────────────────────
    # Serien: {series_name: [parsed_file_infos]}
    series_groups: dict[str, list[dict]] = defaultdict(list)
    films: list[str] = []

    for path in files:
        # Preflight und Renamer muessen denselben Serienparser verwenden.
        # Dadurch stimmen Suchname, Seriengruppierung und die anschliessende
        # Online-Metadatensuche exakt mit dem Renamer ueberein.
        parsed = parse_series_release_name(user_path_name(path))
        if parsed and parsed.series:
            series_groups[parsed.series].append({
                "path": path,
                "season": parsed.season,
                "episode": parsed.episode,
                "episodes": [parsed.episode],
                "year": parsed.year,
                "release_warnings": release_style_warnings(user_path_name(path)),
            })
        else:
            films.append(path)

    # Serien-Gruppen anzeigen
    if series_groups:
        grp_lbl = QLabel(
            f"<b>Serien</b> <span style='color:#64748b;'>"
            f"({len(series_groups)} Gruppe{'n' if len(series_groups)>1 else ''})</span>")
        inner_v.addWidget(grp_lbl)

        for sn, entries in sorted(series_groups.items()):
            w = SeriesGroupWidget(
                sn, entries, tv_path, anime_path,
                default_type=series_default_type,
            )
            w.set_metadata_refresh_callback(dialog._lookup_widget_metadata)
            w.setStyleSheet(
                "SeriesGroupWidget{background:#f0f9ff;"
                "border:1px solid #bae6fd;border-radius:5px;}")
            dialog._widgets.append(w)
            inner_v.addWidget(w)

    # Filme anzeigen
    if films:
        if series_groups:
            inner_v.addWidget(_sep())
        film_lbl = QLabel(
            f"<b>Filme</b> <span style='color:#64748b;'>"
            f"({len(films)} Film{'e' if len(films)>1 else ''})</span>")
        inner_v.addWidget(film_lbl)

        for path in films:
            w = FilmWidget(path, filme_path, release_warnings=release_style_warnings(user_path_name(path)))
            w.setStyleSheet(
                "FilmWidget{background:#fdf4ff;"
                "border:1px solid #e9d5ff;border-radius:5px;}")
            dialog._widgets.append(w)
            inner_v.addWidget(w)

    inner_v.addStretch()
    scroll.setWidget(inner)
    v.addWidget(scroll)

    # Hinweis
    hint = QLabel(
        "💡 Bestehende Serienordner werden automatisch erkannt. "
        "Neue Ordner werden beim Verschieben angelegt.")
    hint.setStyleSheet("color:#475569; font-size:11px;")
    v.addWidget(hint)

    dialog._save_report_cb = QCheckBox("📋 Preflight-Bericht speichern")
    dialog._save_report_cb.setToolTip(
        "Speichert vor dem Start eine lokale Zusammenfassung mit Eingaben, "
        "Zielpfaden, Regelvorschau und Warnungen."
    )
    dialog._save_report_cb.setChecked(
        QSettings(APP_ORG, APP_NAME).value(
            SET_KEY_PREFLIGHT_SAVE_REPORT, False, type=bool
        )
    )
    v.addWidget(dialog._save_report_cb)

    # Buttons
    btns = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok |
        QDialogButtonBox.StandardButton.Cancel)
    btns.button(QDialogButtonBox.StandardButton.Ok).setText("✅ Starten")
    btns.button(QDialogButtonBox.StandardButton.Cancel).setText("Abbrechen")
    btns.accepted.connect(dialog._accept_with_validation)
    btns.rejected.connect(dialog.reject)
    v.addWidget(btns)
    QTimer.singleShot(0, dialog._start_online_metadata_lookup)
