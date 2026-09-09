# -*- coding: utf-8 -*-
"""Seriengruppen-Widget des Move-Preflights."""
from __future__ import annotations
from typing import Any
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QLineEdit, QPushButton, QInputDialog
from ..core.paths import user_path_name
from .preflight_widget_common import _fmt_path, _series_root_from_input, _series_season_target, _base_path_key
from .preflight_series_choices import NO_SERIES_FOLDER_CHOICE, hide_series_folder_choices, install_series_folder_choice, selected_series_folder_choice, show_series_folder_choices, validate_series_folder_choice

class SeriesGroupWidget(QWidget):
    def __init__(
        self,
        series_name: str,
        entries: list[dict],
        tv_path: str | None,
        anime_path: str | None,
        default_type: str = "Anime",
        parent=None,
    ):
        super().__init__(parent)
        self.entries = entries
        self.tv_path = tv_path
        self.anime_path = anime_path
        self._default_type = default_type
        self._metadata_original_name = series_name
        self._resolved_series_key: tuple[str, str] | None = None
        self._resolved_series_dir: str | None = None
        self._library_path_warning = ""
        self._library_name_applied = False
        self._folder_choice_combo: QComboBox | None = None
        self._metadata_refresh_callback = None
        self._build(series_name)

    def _build(self, series_name: str):
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 6, 8, 6)
        v.setSpacing(4)

        count = len(self.entries)
        seasons = sorted(
            {
                entry["season"]
                for entry in self.entries
                if entry.get("season") is not None
            }
        )
        season_text = ", ".join(f"{season:02d}" for season in seasons) if seasons else "?"

        ep_lbl = QLabel(
            f"📺  <b>{series_name}</b>"
            f"  <span style='color:#64748b;'>"
            f"({count} Folge{'n' if count != 1 else ''}, "
            f"Staffeln: {season_text})"
            f"</span>"
        )
        ep_lbl.setTextFormat(Qt.TextFormat.RichText)
        ep_lbl.setWordWrap(True)
        v.addWidget(ep_lbl)

        shown = self.entries[:3]
        rest = len(self.entries) - len(shown)

        for entry in shown:
            lbl = QLabel(f"  · {user_path_name(entry['path'])}")
            lbl.setStyleSheet("color:#64748b; font-size:11px;")
            lbl.setWordWrap(True)
            v.addWidget(lbl)

        if rest > 0:
            more = QLabel(f"  · … und {rest} weitere Datei{'en' if rest != 1 else ''}")
            more.setStyleSheet("color:#94a3b8; font-size:11px;")
            v.addWidget(more)

        release_warnings = []
        for entry in self.entries:
            release_warnings.extend(list(entry.get("release_warnings") or ()))
        release_warnings = list(dict.fromkeys(release_warnings))
        if release_warnings:
            warning = QLabel(
                "  ⚠️ Nicht normalisierter/Release-Dateiname erkannt: "
                + "; ".join(release_warnings)
                + ". Die Metadatensuche läuft automatisch; bei falscher Serie kann die Suche manuell überschrieben werden."
            )
            warning.setWordWrap(True)
            warning.setStyleSheet("color:#b45309; font-size:11px;")
            v.addWidget(warning)

        row = QHBoxLayout()
        row.addWidget(QLabel("Typ:"))

        self._type_combo = QComboBox()
        self._options: list[tuple[str, str]] = []

        if self.tv_path:
            self._type_combo.addItem("📺 TV")
            self._options.append(("TV", self.tv_path))

        if self.anime_path:
            self._type_combo.addItem("🎌 Anime")
            self._options.append(("Anime", self.anime_path))

        _default_idx = next(
            (i for i, (t, _) in enumerate(self._options)
             if t.lower() == self._default_type.lower()),
            0,
        )
        self._type_combo.setCurrentIndex(_default_idx)

        self._type_combo.setMinimumWidth(120)
        self._type_combo.currentIndexChanged.connect(self._update_preview)
        row.addWidget(self._type_combo)

        row.addWidget(QLabel("Serie:"))
        self._series_edit = QLineEdit(series_name)
        self._series_edit.textChanged.connect(self._series_text_changed)
        row.addWidget(self._series_edit, 1)
        self._manual_search_btn = QPushButton("🔍 Eigene Seriensuche")
        self._manual_search_btn.clicked.connect(self._manual_series_search)
        row.addWidget(self._manual_search_btn)

        v.addLayout(row)

        self._preview = QLabel()
        self._preview.setWordWrap(True)
        v.addWidget(self._preview)
        self._update_preview()

        self._metadata_hint = QLabel()
        self._metadata_hint.setWordWrap(True)
        self._metadata_hint.setStyleSheet("color:#2563eb; font-size:11px;")
        self._metadata_hint.setVisible(False)
        v.addWidget(self._metadata_hint)

        install_series_folder_choice(self, v)

    def set_metadata_refresh_callback(self, callback) -> None:
        self._metadata_refresh_callback = callback

    def _manual_series_search(self) -> None:
        current = self._series_edit.text().strip()
        query, ok = QInputDialog.getText(
            self, "Eigene Seriensuche", "Serien-Suchbegriff:", text=current
        )
        query = str(query or "").strip()
        if not ok or not query:
            return
        self._resolved_series_key = None
        self._resolved_series_dir = None
        self._metadata_original_name = query
        if self.__dict__.get("_folder_choice_combo") is not None:
            hide_series_folder_choices(self)
        self._series_edit.setText(query)
        if callable(self._metadata_refresh_callback):
            self._metadata_refresh_callback(self)

    def _update_preview(self):
        t = self._preview_target_dir()
        if t:
            self._preview.setText(f"  ℹ️ {_fmt_path(t)}")
            self._preview.setStyleSheet("color:#059669; font-size:11px;")
        else:
            self._preview.setText("  ⚠️ Kein Zielpfad – wird nicht verschoben")
            self._preview.setStyleSheet("color:#dc2626; font-size:11px;")

    update_preview = _update_preview

    def _series_text_changed(self) -> None:
        combo = self.__dict__.get("_folder_choice_combo")
        if combo is not None and combo.isVisible():
            hide_series_folder_choices(self)
            self._resolved_series_key = None
            self._resolved_series_dir = None
        self._update_preview()

    def _series_root_dir(self) -> str | None:
        base = self._current_base_path()
        sn = self._series_edit.text().strip()
        if not base or not sn:
            return None

        key = (base, sn)
        if self._resolved_series_key == key and self._resolved_series_dir:
            return self._resolved_series_dir
        choice = selected_series_folder_choice(self, base, sn)
        if choice is not NO_SERIES_FOLDER_CHOICE:
            return str(choice or "") or None
        return _series_root_from_input(base, sn)

    def _current_base_path(self) -> str | None:
        if not self._options:
            return None
        idx = self._type_combo.currentIndex()
        if idx < 0 or idx >= len(self._options):
            return None
        return self._options[idx][1]

    def _ordered_search_bases(self) -> list[dict[str, str]]:
        """Aktuell gewaehlten Serienbereich zuerst, danach die weiteren Bereiche."""
        if not self._options:
            return []
        current_idx = self._type_combo.currentIndex()
        ordered: list[tuple[str, str]] = []
        if 0 <= current_idx < len(self._options):
            ordered.append(self._options[current_idx])
        for option in self._options:
            if option not in ordered:
                ordered.append(option)

        seen: set[str] = set()
        result: list[dict[str, str]] = []
        for type_name, base in ordered:
            key = _base_path_key(base)
            if not key or key in seen:
                continue
            seen.add(key)
            result.append({"type": type_name, "base": base})
        return result

    def _select_base_path(self, base: str) -> bool:
        wanted = _base_path_key(base)
        if not wanted:
            return False
        for idx, (_type_name, option_base) in enumerate(self._options):
            if _base_path_key(option_base) != wanted:
                continue
            setter = getattr(self._type_combo, "setCurrentIndex", None)
            if callable(setter) and self._type_combo.currentIndex() != idx:
                setter(idx)
            return True
        return False

    def _select_type_name(self, type_name: str) -> bool:
        wanted = str(type_name or "").strip().casefold()
        if not wanted:
            return False
        for idx, (option_type, _option_base) in enumerate(self.__dict__.get("_options", [])):
            if option_type.casefold() != wanted:
                continue
            setter = getattr(self._type_combo, "setCurrentIndex", None)
            if callable(setter) and self._type_combo.currentIndex() != idx:
                setter(idx)
            return True
        return False

    def metadata_lookup_job(self) -> tuple[str, str, Any] | None:
        base = self._current_base_path()
        series_name = self._series_edit.text().strip()
        if not base or not series_name:
            return None
        key = f"{id(self)}:{base}:{series_name}"
        return (
            "series",
            key,
            {
                "base": base,
                "series_name": series_name,
                "search_bases": self._ordered_search_bases(),
                "year": self._single_entry_year(),
            },
        )

    def _single_entry_year(self) -> int | None:
        years = {int(entry["year"]) for entry in self.__dict__.get("entries", []) if entry.get("year")}
        return years.pop() if len(years) == 1 else None

    def mark_metadata_lookup_started(self, online_lookup: bool = True) -> None:
        if online_lookup:
            self._metadata_hint.setText(
                "  🌐 Suche: bestehende Serienordner und Online-Serienjahr werden geladen …"
            )
        else:
            self._metadata_hint.setText(
                "  ℹ️ Bestehende Serienordner werden im Hintergrund gesucht …"
            )
        self._metadata_hint.setVisible(True)

    def mark_metadata_lookup_failed(self, message: str = "") -> None:
        detail = f" – {message}" if message else ""
        self._metadata_hint.setText(f"  🌐 Online-Metadaten: Serienjahr konnte nicht geladen werden{detail}")
        self._metadata_hint.setVisible(True)

    def mark_existing_series_dir_not_found(self) -> None:
        warning = self.__dict__.get("_library_path_warning", "")
        suffix = f"\n  ⚠️ {warning}" if warning else ""
        self._metadata_hint.setText(f"  ℹ️ Kein bestehender Serienordner gefunden – Ziel wird neu angelegt.{suffix}")
        self._metadata_hint.setVisible(True)

    def mark_library_path_warning(self, message: str) -> None:
        detail = str(message or "").strip()
        if not detail:
            return
        self._library_path_warning = detail
        self._metadata_hint.setText(f"  ⚠️ Mediathek-Datenbank: {detail}")
        self._metadata_hint.setStyleSheet("color:#b45309; font-size:11px;")
        self._metadata_hint.setVisible(True)

    def apply_unusable_library_series_match(
        self,
        *,
        message: str,
        series_name: str,
        suggested_series_name: str = "",
        base: str = "",
        base_type: str = "",
    ) -> None:
        if self._series_edit.text().strip() != series_name:
            return
        if base:
            self._select_base_path(base)
        elif base_type:
            self._select_type_name(base_type)

        suggestion = str(suggested_series_name or "").strip()
        if suggestion and self._series_edit.text().strip() == series_name:
            self._series_edit.setText(suggestion)
            self._library_name_applied = True

        self.mark_library_path_warning(message)
        self._update_preview()

    def apply_existing_series_dir(
        self,
        existing_dir: str,
        base: str,
        series_name: str,
        base_type: str = "",
        source: str = "folder_search",
        notice: str = "",
    ) -> None:
        if self._series_edit.text().strip() != series_name:
            return
        if not self._select_base_path(base):
            return
        if self.__dict__.get("_folder_choice_combo") is not None:
            hide_series_folder_choices(self)
        self._resolved_series_key = (base, series_name)
        self._resolved_series_dir = existing_dir
        type_hint = f" ({base_type})" if base_type else ""
        source_key = str(source or "").casefold()
        if source_key in {"database", "mediathek-db", "mediathek_datenbank"}:
            source_text = "🗄 Zielquelle: Mediathek-Datenbank"
        else:
            source_text = "📁 Zielquelle: Ordnersuche"
        notice_text = str(notice or "").strip()
        warning_text = str(self.__dict__.get("_library_path_warning", "") or "").strip()
        # Erfolgreich geprüfte/normalisierte DB-Pfade sind reine Information.
        # Ein zuvor erkannter unbrauchbarer DB-Pfad bleibt dagegen eine Warnung.
        if notice_text:
            note = f"\n  ℹ️ {notice_text}"
        elif warning_text:
            note = f"\n  ⚠️ {warning_text}"
        else:
            note = ""
        self._metadata_hint.setText(f"  {source_text}{type_hint} – {_fmt_path(existing_dir)}{note}")
        self._metadata_hint.setVisible(True)
        self._update_preview()

    def apply_existing_series_dir_choices(
        self,
        *,
        choices: list[dict],
        series_name: str,
        suggested_series_name: str = "",
    ) -> None:
        show_series_folder_choices(
            self,
            choices=choices,
            series_name=series_name,
            suggested_series_name=suggested_series_name,
        )

    def apply_online_metadata_suggestion(self, suggestion) -> None:
        if suggestion is None or not getattr(suggestion, "first_air_year", None):
            warning = self.__dict__.get("_library_path_warning", "")
            suffix = f"\n  ⚠️ {warning}" if warning else ""
            self._metadata_hint.setText(f"  🌐 Online-Metadaten: kein passender Serientreffer{suffix}")
            self._metadata_hint.setVisible(True)
            return
        if self._series_edit.text().strip() != self._metadata_original_name:
            warning = self.__dict__.get("_library_path_warning", "")
            suffix = f"\n  ⚠️ {warning}" if warning else ""
            if self.__dict__.get("_library_name_applied", False):
                self._metadata_hint.setText(
                    f"  🌐 Online-Metadaten: Vorschlag nicht übernommen – Mediathek-Serienname hat Vorrang.{suffix}"
                )
                self._metadata_hint.setVisible(True)
                return
            self._metadata_hint.setText(
                f"  🌐 Online-Metadaten: Vorschlag nicht übernommen – Feld wurde manuell geändert.{suffix}"
            )
            self._metadata_hint.setVisible(True)
            return

        self._series_edit.setText(suggestion.folder_name)
        warning = self.__dict__.get("_library_path_warning", "")
        suffix = f"\n  ⚠️ {warning}" if warning else ""
        self._metadata_hint.setText(
            f"  🌐 Online-Metadaten: Serienjahr vorgeschlagen – {suggestion.folder_name}{suffix}"
        )
        self._metadata_hint.setVisible(True)
        self._update_preview()

    def _preview_target_dir(self) -> str | None:
        base_dir = self._series_root_dir()
        if not base_dir:
            return None
        first_entry = next((entry for entry in self.entries if entry.get("season") is not None), None)
        if not first_entry:
            return None
        return _series_season_target(base_dir, first_entry["season"])

    def get_planned_targets(self) -> dict[str, str | dict]:
        base_dir = self._series_root_dir()
        if not base_dir:
            return {}

        result: dict[str, str] = {}
        for entry in self.entries:
            season = entry.get("season")
            if season is None:
                continue
            target_dir = _series_season_target(base_dir, season)
            if target_dir:
                result[entry["path"]] = target_dir

        return result

    def validate(self) -> tuple[bool, str]:
        return validate_series_folder_choice(self)
