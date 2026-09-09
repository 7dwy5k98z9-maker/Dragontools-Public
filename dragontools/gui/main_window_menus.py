# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt6.QtGui import QAction, QKeySequence, QShortcut

from ..core.settings import APP_ORG, APP_NAME, APP_VERSION


class MainWindowMenuMixin:
    def _init_menu(self):
        mb = self.menuBar()
        self._build_file_menu(mb)
        self._build_settings_menu(mb)
        self._build_rules_menu(mb)
        self._build_online_metadata_menu(mb)
        self._build_media_library_menu(mb)
        self._build_profile_menu(mb)
        self._build_view_menu(mb)
        self._build_tools_menu(mb)
        self._build_zoom_menu(mb)
        self._build_help_menu(mb)
        self.statusBar().showMessage(f"© 2026 – Dragon Tools V{APP_VERSION} bereit.")

    def _build_file_menu(self, menubar) -> None:
        fm = menubar.addMenu("📂 Datei")
        fm.addAction(QAction("🔄 Standardwerte wiederherstellen", self,
                             triggered=self._reset_defaults,
                             shortcut=QKeySequence("Ctrl+R")))
        fm.addAction(QAction("🔁 Offene Restqueue importieren", self,
                             triggered=self._open_unfinished_job_journal))
        fm.addAction(QAction("🚚 Offene Verschiebequeue importieren", self,
                             triggered=self._open_unfinished_move_journal))
        fm.addSeparator()
        fm.addAction(QAction("❌ Beenden", self,
                             triggered=self.close,
                             shortcut=QKeySequence("Ctrl+Q")))

    def _build_settings_menu(self, menubar) -> None:
        sm = menubar.addMenu("⚙️ Einstellungen")
        sm.addAction(QAction("💾 Speicherpfade festlegen", self,
                             triggered=self._open_settings_paths))
        sm.addAction(QAction("📝 Loggingordner festlegen", self,
                             triggered=self._open_settings_logging))
        sm.addAction(QAction("🧹 Log-Bereinigung", self,
                             triggered=self._open_settings_log_cleanup))
        sm.addAction(QAction("🛠️ Werkzeugpfade definieren", self,
                             triggered=self._open_settings_tools))
        sm.addAction(QAction("⚙️ Standardwerte", self,
                             triggered=self._open_settings_defaults))
        sm.addAction(QAction("⚙️ Parallele Bearbeitung", self,
                             triggered=self._open_settings_parallel))
        sm.addAction(QAction("🗄 Mediathek-Datenbank", self,
                             triggered=self._open_settings_media_library))
        sm.addAction(QAction("🎞 Jellyfin NFO / Trickplay", self,
                             triggered=self._open_settings_postprocess))
        sm.addAction(QAction("🔎 Quellbildprüfung", self,
                             triggered=self._open_settings_source_visual))
        sm.addAction(QAction("💾 Speichereinstellungen", self,
                             triggered=self._open_settings_save))
        sm.addAction(QAction("📦 Ausgabecontainer", self,
                             triggered=self._open_settings_containers))
        sm.addAction(QAction("✂️ Auto-Crop", self,
                             triggered=self._open_settings_autocrop))
        sm.addAction(QAction("✅ Output-Validierung / Reparatur", self,
                             triggered=self._open_settings_validation))
        sm.addAction(QAction("📁 Verschieben – Konfliktverhalten", self,
                             triggered=self._open_settings_move_conflict))
        sm.addAction(QAction("🎬 IMAX Auto-Erkennung", self,
                             triggered=self._open_settings_imax))
        sm.addAction(QAction("⏱ Timeouts …", self,
                             triggered=self._open_timeout_settings))
        sm.addSeparator()
        sm.addAction(QAction("🌐 Globales Einstellungsfenster öffnen", self,
                             triggered=self._open_settings))

        sm.addSeparator()
        sm.addAction(QAction("Backup exportieren", self,
                             triggered=self._export_backup))
        sm.addAction(QAction("Backup wiederherstellen", self,
                             triggered=self._restore_backup))

    def _build_rules_menu(self, menubar) -> None:
        rm = menubar.addMenu("🧱 Regeln")
        rm.addAction(QAction("📺 Serien-Erkennung", self,
                             triggered=self._open_rules_series))
        rm.addAction(QAction("🎞 Renamer-Regeln", self,
                             triggered=self._open_rules_renamer))
        rm.addAction(QAction("🔊 Audio-Regeln", self,
                             triggered=self._open_rules_audio))
        rm.addAction(QAction("💬 Untertitel-Regeln", self,
                             triggered=self._open_rules_subtitles))
        rm.addAction(QAction("🏷️ Untertitel-Flag", self,
                             triggered=self._open_rules_flags))
        rm.addSeparator()
        rm.addAction(QAction("🌐 Globales Regelfenster öffnen", self,
                             triggered=self._open_rules))

    def _build_online_metadata_menu(self, menubar) -> None:
        mm = menubar.addMenu("🌐 Online-Metadaten")
        mm.addAction(QAction("🎞 Renamer öffnen", self,
                             triggered=self._open_movie_renamer_tab))
        mm.addSeparator()
        mm.addAction(QAction("🔑 Metadaten-Zugriff einrichten", self,
                             triggered=self._open_online_metadata_settings))
        mm.addAction(QAction("🔌 Metadaten-Verbindungen testen", self,
                             triggered=self._test_tmdb_connection))
        mm.addAction(QAction("🔎 Titel online suchen", self,
                             triggered=self._search_online_metadata))
        mm.addAction(QAction("🧹 Metadaten-Cache leeren", self,
                             triggered=self._clear_metadata_cache))
        mm.addSeparator()
        mm.addAction(QAction("🎞 TMDB im Browser öffnen", self,
                             triggered=lambda: self._open_url("https://www.themoviedb.org")))
        mm.addAction(QAction("📺 TheTVDB im Browser öffnen", self,
                             triggered=lambda: self._open_url("https://thetvdb.com")))

    def _build_media_library_menu(self, menubar) -> None:
        lm = menubar.addMenu("🗄 Mediathek-DB")
        lm.addAction(QAction("📊 Status / Import öffnen", self,
                             triggered=lambda: self._open_media_library("status")))
        lm.addAction(QAction("🧭 Pfad-Mapping öffnen", self,
                             triggered=lambda: self._open_media_library("mapping")))
        lm.addAction(QAction("🔎 Mediathek durchsuchen", self,
                             triggered=lambda: self._open_media_library("search")))
        lm.addAction(QAction("📝 SQL bearbeiten", self,
                             triggered=lambda: self._open_media_library("sql")))

    def _build_profile_menu(self, menubar) -> None:
        pm = menubar.addMenu("📁 Profile")
        pm.addAction(QAction("📁 Profilverwaltungsfenster öffnen", self,
                             triggered=self._open_profile_manager))

    def _build_view_menu(self, menubar) -> None:
        vm = menubar.addMenu("👁 Ansicht")
        vm.addSection("Registerkarten")
        self._init_tab_visibility_actions(vm)
        vm.addSeparator()
        vm.addAction(QAction("🗂 Registerkarten verwalten", self,
                             triggered=self._open_tab_manager))
        vm.addSeparator()
        self.act_dark = QAction("🌙 Dunkler Modus", self, checkable=True)
        self.act_dark.toggled.connect(self._toggle_dark)
        vm.addAction(self.act_dark)
        vm.addSeparator()
        vm.addSection("Externe Programme")
        vm.addAction(QAction("🎬 HandBrake öffnen", self,
                             triggered=lambda: self._launch_external("HandBrake.exe")))
        vm.addAction(QAction("📝 RMTS öffnen", self,
                             triggered=lambda: self._launch_external("RenameMyTVSeries.exe")))
        vm.addAction(QAction("🧰 Remux – MKVToolNix öffnen", self,
                             triggered=lambda: self._launch_external("mkvtoolnix-gui.exe")))
        vm.addAction(QAction("🎞 TMDB im Browser öffnen", self,
                             triggered=lambda: self._open_url("https://www.themoviedb.org")))

    def _init_tab_visibility_actions(self, menu) -> None:
        self._tab_actions: dict[str, QAction] = {}
        for key, label in [
            ("h265", "🎬 H.265 / DV / HDR10+"),
            ("h264", "🎞 H.264"),
            ("av1", "🧬 AV1"),
            ("iso", "💿 ISO"),
            ("merge", "🧩 Merge"),
            ("mp4_remux", "📦 MP4-Remux"),
            ("audio_muxer", "🎚 Audio Muxer"),
            ("audio_video_matcher", "🎧 Audio-Video-Matcher"),
            ("subtitle", "💬 Untertitel"),
            ("movie_renamer", "🎞 Renamer"),
            ("quality_tester", "🧪 Qualitätstester"),
        ]:
            act = QAction(label, self, checkable=True)
            from PyQt6.QtCore import QSettings as _QS
            act.setChecked(_QS(APP_ORG, APP_NAME).value(f"tabs/visible/{key}", True, type=bool))
            act.toggled.connect(lambda on, k=key: self._toggle_tab(k, on))
            menu.addAction(act)
            self._tab_actions[key] = act

    def _build_tools_menu(self, menubar) -> None:
        wm = menubar.addMenu("🛠 Werkzeuge")
        wm.addAction(QAction("🔎 System prüfen / Werkzeuge  [F9]", self,
                             triggered=self._check_tools))
        wm.addAction(QAction("🧪 Erweiterter Systemtest mit Mini-Dateien", self,
                             triggered=self._check_tools_extended))
        wm.addAction(QAction("🧪 Regel-/Profil-Simulator aktuelle Queue", self,
                             triggered=self._show_active_queue_rule_test))
        wm.addAction(QAction("🩺 Laufenden Job diagnostizieren", self,
                             triggered=self._show_running_job_diagnostics))
        wm.addAction(QAction("🧪 Diagnosepaket erstellen", self,
                             triggered=self._create_diagnostic_package))
        wm.addAction(QAction("🧪 Qualitätstester öffnen", self,
                             triggered=self._open_quality_tester_tab))
        wm.addAction(QAction("🎧 Audio-Video-Matcher öffnen", self,
                             triggered=self._open_audio_video_matcher_tab))
        wm.addAction(QAction("✅ Release-/Build prüfen", self,
                             triggered=self._check_release_build))
        wm.addSeparator()
        wm.addAction(QAction("🎬 HandBrake öffnen", self,
                             triggered=lambda: self._launch_external("HandBrake.exe")))
        wm.addAction(QAction("📝 RMTS öffnen", self,
                             triggered=lambda: self._launch_external("RenameMyTVSeries.exe")))
        wm.addAction(QAction("🧰 Remux – MKVToolNix öffnen", self,
                             triggered=lambda: self._launch_external("mkvtoolnix-gui.exe")))

    def _build_zoom_menu(self, menubar) -> None:
        zm = menubar.addMenu("🔍 Zoom-Fenster")
        zm.addAction(QAction("🗂 Warteschlange", self,
                             triggered=self._open_convert_queue,
                             shortcut=QKeySequence("Ctrl+Shift+Q")))
        zm.addAction(QAction("📋 Logging-Fenster", self,
                             triggered=self._open_log_zoom_window))

    def _build_help_menu(self, menubar) -> None:
        hm = menubar.addMenu("❓ Hilfe")
        hm.addAction(QAction("📖 Hilfe  [F1]", self, triggered=self._open_help))
        hm.addAction(QAction("📘 PDF-Handbuch öffnen  [F2]", self, triggered=self._open_handbook))
        hm.addAction(QAction("⌨️ Shortcuts", self, triggered=self._open_shortcuts))
        hm.addAction(QAction("📝 Änderungshistorie V9  [F12]", self, triggered=self._open_changelog))
        hm.addAction(QAction("🕘 Änderungshistorie Legacy V8  [F11]", self, triggered=self._open_legacy_changelog))
        hm.addSeparator()
        hm.addAction(QAction("🔄 Nach Updates suchen", self, triggered=self._check_for_updates))
        hm.addSeparator()
        hm.addAction(QAction("ℹ️ Über", self, triggered=self._about))

    def _init_shortcuts(self):
        shortcuts = [
            ("F1",              self._open_help),
            ("F2",              self._open_handbook),
            ("F9",              self._check_tools),
            ("F11",             self._open_legacy_changelog),
            ("F12",             self._open_changelog),
            ("Ctrl+Q",          self.close),
            ("Ctrl+W",          self._close_current_tab),
            ("Ctrl+Shift+T",    self._reopen_last_tab),
            ("Ctrl+Shift+A",    self._reopen_all_tabs),
            ("Ctrl+R",          self._reset_defaults),
            ("Delete",          self._delete_selected_file),
        ]
        for key, slot in shortcuts:
            s = QShortcut(QKeySequence(key), self)
            s.activated.connect(slot)

    def _shortcut_entries(self) -> list[tuple[str, str, str]]:
        return [
            ("F1", "Hilfe öffnen", "Hilfe"),
            ("F2", "PDF-Handbuch öffnen", "Hilfe"),
            ("F9", "System prüfen / Werkzeuge", "Werkzeuge"),
            ("F11", "Legacy-Changelog V8 öffnen", "Hilfe"),
            ("F12", "Changelog V9 öffnen", "Hilfe"),
            ("Ctrl+Q", "Anwendung beenden", "Datei"),
            ("Ctrl+W", "Aktuellen Tab schließen", "Ansicht"),
            ("Ctrl+Shift+Q", "Warteschlange öffnen", "Zoom-Fenster"),
            ("Ctrl+Shift+T", "Letzten Tab wieder öffnen", "Ansicht"),
            ("Ctrl+Shift+A", "Alle Tabs wieder öffnen", "Ansicht"),
            ("Ctrl+R", "Standardwerte wiederherstellen", "Datei"),
            ("Delete", "Markierte Datei entfernen", "Convert"),
        ]
