# -*- coding: utf-8 -*-
"""Tab-, Lazy-Loading- und Converter-Handoff-Logik des MainWindow."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTabWidget, QTabBar, QWidget, QLabel, QMessageBox

from .tab_manager import TabManagerDialog, get_visible_tabs


class _TabBar(QTabBar):
    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.MiddleButton:
            idx = self.tabAt(e.pos())
            if idx >= 0:
                self.tabCloseRequested.emit(idx)
        super().mouseReleaseEvent(e)


class MainWindowTabsMixin:
    """Kapselt Tab-Lifecycle, Lazy Loading und Tab-Handoffs."""

    def _init_tabs(self):
        self.tabs = QTabWidget()
        self.tabs.setTabBar(_TabBar())
        self.tabs.tabBar().setMovable(True)
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self._on_tab_close)
        self.tabs.currentChanged.connect(self._on_tab_activate)
        self.setCentralWidget(self.tabs)

        visible = get_visible_tabs()

        # Tabs in fester Reihenfolge anlegen – aber Widget erst bei Aktivierung laden
        self._tab_defs = [
            ("h265",     "H.265 / DV / HDR10+"),
            ("h264",     "H.264"),
            ("av1",      "AV1"),
            ("iso",      "ISO"),
            ("merge",    "Merge"),
            ("mp4_remux", "MP4-Remux"),
            ("audio_muxer", "Audio Muxer"),
            ("audio_video_matcher", "Audio-Video-Matcher"),
            ("subtitle", "Untertitel"),
            ("movie_renamer", "Renamer"),
            ("quality_tester", "Qualitätstester"),
        ]

        for key, label in self._tab_defs:
            if not visible.get(key, True):
                continue
            placeholder = self._make_placeholder(label)
            self._tab_widgets[key] = None   # None = noch nicht geladen
            self.tabs.addTab(placeholder, label)
            self.tabs.tabBar().setTabData(self.tabs.count()-1, key)

        # Start-Tab anhand von defaults/codec bestimmen.
        # "defaults/codec" (h265 / h264 / av1) legt fest, welcher Converter-Tab
        # beim App-Start aktiv ist. Ist der gewünschte Tab nicht sichtbar oder
        # nicht vorhanden, fällt die App auf den ersten verfügbaren Tab zurück.
        default_codec = self._settings.value("defaults/codec", "h265", type=str)
        start_idx = 0  # Fallback: erster Tab
        for i in range(self.tabs.count()):
            if self.tabs.tabBar().tabData(i) == default_codec:
                start_idx = i
                break
        if self.tabs.count() > 0:
            self.tabs.setCurrentIndex(start_idx)
            self._ensure_tab_loaded(start_idx)

    def _make_placeholder(self, label: str) -> QWidget:
        """Leerer Platzhalter mit Banner – wird beim ersten Klick ersetzt."""
        w = QWidget()
        lbl = QLabel(f"🐉  {label} wird geladen …")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("font-size:16px;color:#888;")
        from PyQt6.QtWidgets import QVBoxLayout
        v = QVBoxLayout(w); v.addWidget(lbl)
        return w

    def _on_tab_activate(self, idx: int) -> None:
        self._ensure_tab_loaded(idx)

    def _ensure_tab_loaded(self, idx: int) -> None:
        """Lädt das Widget für einen Tab wenn es noch nicht geladen ist."""
        if idx < 0 or idx >= self.tabs.count():
            return
        key = self.tabs.tabBar().tabData(idx)
        if key is None:
            return
        if self._tab_widgets.get(key) is not None:
            return   # schon geladen

        widget = self._create_tab_widget(key)
        if widget is None:
            return
        self._tab_widgets[key] = widget
        self.tabs.removeTab(idx)
        self.tabs.insertTab(idx, widget, self.tabs.tabText(idx) if False else self._tab_label(key))
        self.tabs.tabBar().setTabData(idx, key)
        self.tabs.setCurrentIndex(idx)

    def _tab_label(self, key: str) -> str:
        return {
            "h265":     "H.265 / DV / HDR10+",
            "h264":     "H.264",
            "av1":      "AV1",
            "iso":      "ISO",
            "merge":    "Merge",
            "mp4_remux": "MP4-Remux",
            "audio_muxer": "Audio Muxer",
            "audio_video_matcher": "Audio-Video-Matcher",
            "subtitle": "Untertitel",
            "movie_renamer": "Renamer",
            "quality_tester": "Qualitätstester",
        }.get(key, key)

    def _create_tab_widget(self, key: str) -> QWidget | None:
        """Factory: erzeugt das echte Widget für einen Tab-Key."""
        try:
            if key in ("h265", "h264", "av1"):
                from .convert_widget import ConvertWidget
                return ConvertWidget(key)
            elif key == "iso":
                from .iso_widget import ISOWidget
                widget = ISOWidget()
                widget.handoff_requested.connect(self._handoff_iso_to_converter)
                return widget
            elif key == "merge":
                from .merge_widget import MergeWidget
                return MergeWidget()
            elif key == "mp4_remux":
                from .mp4_remux_widget import MP4RemuxWidget
                return MP4RemuxWidget()
            elif key == "audio_muxer":
                from .audio_muxer_widget import AudioMuxerWidget
                return AudioMuxerWidget()
            elif key == "audio_video_matcher":
                from .audio_video_matcher_widget import AudioVideoMatcherWidget
                return AudioVideoMatcherWidget()
            elif key == "subtitle":
                from .subtitle_widget import SubtitleWidget
                return SubtitleWidget()
            elif key == "movie_renamer":
                from .movie_renamer_widget import MovieRenamerWidget
                return MovieRenamerWidget()
            elif key == "quality_tester":
                from .quality_tester_widget import QualityTesterWidget
                return QualityTesterWidget()
        except Exception as e:
            lbl = QLabel(f"Fehler beim Laden: {e}")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            return lbl
        return None

    def _on_tab_close(self, idx: int):
        if self.tabs.count() <= 1:
            return   # letzten Tab nicht schließen
        key   = self.tabs.tabBar().tabData(idx)
        if key:
            self._closed_tabs.append((key, idx))
        self.tabs.removeTab(idx)
        self._set_tab_visible_setting(key, False)

    def _close_current_tab(self):
        self._on_tab_close(self.tabs.currentIndex())

    def _reopen_last_tab(self):
        if not self._closed_tabs:
            return
        key, preferred_idx = self._closed_tabs.pop()
        self._reopen_tab(key, preferred_idx)

    def _reopen_all_tabs(self):
        if self._closed_tabs:
            closed = sorted(self._closed_tabs, key=lambda item: item[1])
            self._closed_tabs.clear()
            existing_keys = {self.tabs.tabBar().tabData(i) for i in range(self.tabs.count())}
            for key, preferred_idx in closed:
                if key not in existing_keys:
                    self._reopen_tab(key, preferred_idx)
                    existing_keys.add(key)
            return
        visible = get_visible_tabs()
        existing_keys = {self.tabs.tabBar().tabData(i) for i in range(self.tabs.count())}
        for key, _ in self._tab_defs:
            if key not in existing_keys and visible.get(key, True):
                self._reopen_tab(key, self.tabs.count())

    def _reopen_tab(self, key: str, preferred_idx: int):
        self._set_tab_visible_setting(key, True)
        label    = self._tab_label(key)
        existing = self._tab_widgets.get(key)
        if existing is not None:
            idx = min(preferred_idx, self.tabs.count())
            self.tabs.insertTab(idx, existing, label)
            self.tabs.tabBar().setTabData(idx, key)
            self.tabs.setCurrentIndex(idx)
        else:
            placeholder = self._make_placeholder(label)
            self._tab_widgets[key] = None
            idx = min(preferred_idx, self.tabs.count())
            self.tabs.insertTab(idx, placeholder, label)
            self.tabs.tabBar().setTabData(idx, key)
            self.tabs.setCurrentIndex(idx)
            self._ensure_tab_loaded(idx)

    def _set_tab_visible_setting(self, key: str | None, visible: bool) -> None:
        if not key:
            return
        self._settings.setValue(f"tabs/visible/{key}", bool(visible))
        self._settings.sync()
        action = getattr(self, "_tab_actions", {}).get(key)
        if action is not None:
            try:
                previous = action.blockSignals(True)
                action.setChecked(bool(visible))
                action.blockSignals(previous)
            except Exception:
                action.setChecked(bool(visible))

    def _toggle_tab(self, key: str, visible: bool) -> None:
        """Tab direkt aus Ansicht-Menü ein-/ausblenden."""
        self._set_tab_visible_setting(key, visible)
        self._apply_tab_visibility()

    def _open_tab_manager(self):
        dlg = TabManagerDialog(self)
        if dlg.exec():
            self._apply_tab_visibility()

    def _apply_tab_visibility(self):
        visible = get_visible_tabs()
        existing_keys = {self.tabs.tabBar().tabData(i) for i in range(self.tabs.count())}

        # Tabs ausblenden die deaktiviert wurden
        for i in range(self.tabs.count() - 1, -1, -1):
            key = self.tabs.tabBar().tabData(i)
            if key and not visible.get(key, True):
                self.tabs.removeTab(i)
                existing_keys.discard(key)

        # Tabs hinzufügen die aktiviert wurden
        for key, _ in self._tab_defs:
            if visible.get(key, True) and key not in existing_keys:
                self._reopen_tab(key, self.tabs.count())
                existing_keys.add(key)

    def _ensure_converter_widget(self, key: str):
        for i in range(self.tabs.count()):
            if self.tabs.tabBar().tabData(i) == key:
                self.tabs.setCurrentIndex(i)
                self._ensure_tab_loaded(i)
                return self._tab_widgets.get(key)

        self._reopen_tab(key, self.tabs.count())
        for i in range(self.tabs.count()):
            if self.tabs.tabBar().tabData(i) == key:
                self.tabs.setCurrentIndex(i)
                self._ensure_tab_loaded(i)
                return self._tab_widgets.get(key)
        return None

    def _handoff_iso_to_converter(self, paths: list[str]) -> None:
        """Übergibt extrahierte MKV-Dateien aus dem ISO-Tab an einen ConvertWidget-Tab."""
        if not paths:
            return
        # Bevorzugte Reihenfolge: h265 → h264 → av1
        for key in ("h265", "h264", "av1"):
            widget = self._tab_widgets.get(key)
            if widget is not None and widget.__class__.__name__ == "ConvertWidget":
                # Tab in den Vordergrund bringen
                for i in range(self.tabs.count()):
                    if self.tabs.tabBar().tabData(i) == key:
                        self.tabs.setCurrentIndex(i)
                        break
                widget.add_dropped_files(paths)
                n = len(paths)
                self.statusBar().showMessage(
                    f"✅ {n} Datei(en) vom ISO-Tab an {self._tab_label(key)} übergeben.", 5000
                )
                return
        # Kein ConvertWidget geladen → ersten Codec-Tab laden und erneut versuchen
        for key in ("h265", "h264", "av1"):
            for i in range(self.tabs.count()):
                if self.tabs.tabBar().tabData(i) == key:
                    self._ensure_tab_loaded(i)
                    widget = self._tab_widgets.get(key)
                    if widget is not None and widget.__class__.__name__ == "ConvertWidget":
                        self.tabs.setCurrentIndex(i)
                        widget.add_dropped_files(paths)
                        n = len(paths)
                        self.statusBar().showMessage(
                            f"✅ {n} Datei(en) vom ISO-Tab an {self._tab_label(key)} übergeben.", 5000
                        )
                        return
        QMessageBox.warning(
            self,
            "Übergabe fehlgeschlagen",
            "Kein Konverter-Tab (H.265/H.264/AV1) gefunden.\n"
            "Bitte einen Konverter-Tab öffnen und erneut versuchen.",
        )

    def _open_movie_renamer_tab(self) -> None:
        key = "movie_renamer"
        self._settings.setValue(f"tabs/visible/{key}", True)
        if key in getattr(self, "_tab_actions", {}):
            self._tab_actions[key].setChecked(True)
        for i in range(self.tabs.count()):
            if self.tabs.tabBar().tabData(i) == key:
                self.tabs.setCurrentIndex(i)
                self._ensure_tab_loaded(i)
                return
        self._reopen_tab(key, self.tabs.count())

    def _open_quality_tester_tab(self) -> None:
        key = "quality_tester"
        self._settings.setValue(f"tabs/visible/{key}", True)
        if key in getattr(self, "_tab_actions", {}):
            self._tab_actions[key].setChecked(True)
        for i in range(self.tabs.count()):
            if self.tabs.tabBar().tabData(i) == key:
                self.tabs.setCurrentIndex(i)
                self._ensure_tab_loaded(i)
                return
        self._reopen_tab(key, self.tabs.count())

    def _open_audio_video_matcher_tab(self) -> None:
        key = "audio_video_matcher"
        self._settings.setValue(f"tabs/visible/{key}", True)
        if key in getattr(self, "_tab_actions", {}):
            self._tab_actions[key].setChecked(True)
        for i in range(self.tabs.count()):
            if self.tabs.tabBar().tabData(i) == key:
                self.tabs.setCurrentIndex(i)
                self._ensure_tab_loaded(i)
                return
        self._reopen_tab(key, self.tabs.count())
