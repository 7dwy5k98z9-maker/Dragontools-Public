# -*- coding: utf-8 -*-
"""Film-Zielwidget des Move-Preflights."""
from __future__ import annotations

from typing import Any
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QLineEdit

from ..rules.move_rules import default_film_series_name, normalize_relative_move_subpath, resolve_film_target_for_path
from ..core.paths import user_path_name
from .preflight_widget_common import _safe_stem, _fmt_path, _planned_target_entry

class FilmWidget(QWidget):
    """Einzelner Film mit Einzelfilm/Filmreihe Auswahl."""

    def __init__(self, path: str, filme_path: str | None, parent=None, release_warnings=()):
        super().__init__(parent)
        self.path       = path
        self.filme_path = filme_path
        self._release_warnings = tuple(release_warnings or ())
        self._metadata_original_stem = _safe_stem(path)
        self._build()

    def _build(self):
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 6, 8, 6)
        v.setSpacing(4)

        name_lbl = QLabel(f"🎬  <b>{user_path_name(self.path)}</b>")
        name_lbl.setWordWrap(True)
        v.addWidget(name_lbl)
        if self._release_warnings:
            warning = QLabel(
                "  ⚠️ Nicht normalisierter/Release-Dateiname erkannt: "
                + "; ".join(self._release_warnings)
                + ". Die Online-Metadatensuche wird automatisch gestartet."
            )
            warning.setWordWrap(True)
            warning.setStyleSheet("color:#b45309; font-size:11px;")
            v.addWidget(warning)

        stem = self._metadata_original_stem

        row = QHBoxLayout()
        row.addWidget(QLabel("Typ:"))
        self._film_type = QComboBox()
        self._film_type.addItems(["🎬 Einzelfilm", "📚 Filmreihe"])
        self._film_type.setMinimumWidth(140)
        self._film_type.currentIndexChanged.connect(self._on_type_changed)
        row.addWidget(self._film_type)

        row.addWidget(QLabel("Name:"))
        self._film_name = QLineEdit(stem)
        self._film_name.textChanged.connect(self._update_preview)
        row.addWidget(self._film_name, 1)
        v.addLayout(row)

        # Reihenname (nur bei Filmreihe sichtbar)
        self._reihe_row = QHBoxLayout()
        self._reihe_lbl  = QLabel("Reihe:")
        self._reihe_edit = QLineEdit(default_film_series_name(stem))
        self._reihe_edit.textChanged.connect(self._update_preview)
        self._reihe_row.addWidget(self._reihe_lbl)
        self._reihe_row.addWidget(self._reihe_edit, 1)
        reihe_w = QWidget()
        reihe_w.setLayout(self._reihe_row)
        self._reihe_widget = reihe_w
        self._reihe_widget.setVisible(False)
        v.addWidget(self._reihe_widget)

        self._subpath_row = QHBoxLayout()
        self._subpath_lbl = QLabel("Unterordner:")
        self._subpath_edit = QLineEdit()
        self._subpath_edit.setPlaceholderText(
            "optional, relativ, z. B. Trilogie oder Spider-Verse/Miles Morales"
        )
        self._subpath_edit.textChanged.connect(self._update_preview)
        self._subpath_row.addWidget(self._subpath_lbl)
        self._subpath_row.addWidget(self._subpath_edit, 1)
        subpath_w = QWidget()
        subpath_w.setLayout(self._subpath_row)
        self._subpath_widget = subpath_w
        self._subpath_widget.setVisible(False)
        v.addWidget(self._subpath_widget)

        self._preview = QLabel()
        self._preview.setWordWrap(True)
        v.addWidget(self._preview)
        self._update_preview()

        self._metadata_hint = QLabel()
        self._metadata_hint.setWordWrap(True)
        self._metadata_hint.setStyleSheet("color:#2563eb; font-size:11px;")
        self._metadata_hint.setVisible(False)
        v.addWidget(self._metadata_hint)

    def _on_type_changed(self, idx: int):
        self._reihe_widget.setVisible(idx == 1)
        self._subpath_widget.setVisible(idx == 1)
        self._update_preview()

    def _update_preview(self):
        try:
            t = self.get_target_path()
        except ValueError as exc:
            self._preview.setText(f"  [ungültig] {exc}")
            self._preview.setStyleSheet("color:#dc2626; font-size:11px;")
            return
        if t:
            self._preview.setText(f"  → {_fmt_path(t)}")
            self._preview.setStyleSheet("color:#059669; font-size:11px;")
        else:
            self._preview.setText("  ⚠️ Kein Film-Pfad – wird nicht verschoben")
            self._preview.setStyleSheet("color:#dc2626; font-size:11px;")

    def _normalized_relative_subpath(self) -> str:
        return normalize_relative_move_subpath(self._subpath_edit.text())

    def metadata_lookup_job(self) -> tuple[str, str, Any] | None:
        if not self.filme_path:
            return None
        return ("movie", self.path, self.path)

    def mark_metadata_lookup_started(self) -> None:
        self._metadata_hint.setText("  🌐 Online-Metadaten: Film-Metadaten werden im Hintergrund geladen …")
        self._metadata_hint.setVisible(True)

    def mark_metadata_lookup_failed(self, message: str = "") -> None:
        detail = f" – {message}" if message else ""
        self._metadata_hint.setText(f"  🌐 Online-Metadaten: Film-Metadaten konnten nicht geladen werden{detail}")
        self._metadata_hint.setVisible(True)

    def apply_online_metadata_suggestion(self, suggestion) -> None:
        if suggestion is None:
            self._metadata_hint.setText("  🌐 Online-Metadaten: kein passender Filmtreffer")
            self._metadata_hint.setVisible(True)
            return
        if self._film_name.text().strip() != self._metadata_original_stem:
            self._metadata_hint.setText("  🌐 Online-Metadaten: Vorschlag nicht übernommen – Name wurde manuell geändert.")
            self._metadata_hint.setVisible(True)
            return

        self._film_name.setText(suggestion.movie_folder_name)
        if suggestion.has_collection:
            self._film_type.setCurrentIndex(1)
            self._reihe_edit.setText(suggestion.collection_name)
            part_info = (
                f", {suggestion.collection_part_count} Teile"
                if suggestion.collection_part_count else ""
            )
            self._metadata_hint.setText(
                f"  🌐 Online-Metadaten: Filmreihe erkannt – {suggestion.collection_name}{part_info}"
            )
        else:
            self._film_type.setCurrentIndex(0)
            self._metadata_hint.setText("  🌐 Online-Metadaten: Einzelfilm erkannt")
        self._metadata_hint.setVisible(True)
        self._update_preview()

    def get_target_path(self) -> str | None:
        if not self.filme_path:
            return None
        stem = self._film_name.text().strip()
        if not stem:
            return None
        if self._film_type.currentIndex() == 0:
            return resolve_film_target_for_path(
                self.path,
                base_path=self.filme_path,
                film_name=stem,
                mode="single",
            )
        return resolve_film_target_for_path(
            self.path,
            base_path=self.filme_path,
            film_name=stem,
            series_name=self._reihe_edit.text().strip() or stem,
            mode="series",
            relative_subpath=self._normalized_relative_subpath(),
        )

    def validate(self) -> tuple[bool, str | None]:
        try:
            self.get_target_path()
        except ValueError as exc:
            return False, f"{user_path_name(self.path)}: {exc}"
        return True, None

    def get_planned_targets(self) -> dict[str, str | dict]:
        t = self.get_target_path()
        if not t:
            return {}
        if self._film_type.currentIndex() == 0:
            return {self.path: t}
        return {self.path: _planned_target_entry(t, self._normalized_relative_subpath())}
