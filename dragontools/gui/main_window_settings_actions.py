# -*- coding: utf-8 -*-
from __future__ import annotations


class MainWindowSettingsActionsMixin:
    def _exec_settings_dialog(self, *, visible_sections: tuple[str, ...] | None = None, window_title: str | None = None):
        from .settings_dialog import SettingsDialog
        dlg = SettingsDialog(self, visible_sections=visible_sections, window_title=window_title)
        if dlg.exec():
            self._reload_all_paths()
            self.statusBar().showMessage("Einstellungen gespeichert.", 3000)

    def _open_settings(self):
        self._exec_settings_dialog()

    def _open_settings_paths(self):
        self._exec_settings_dialog(visible_sections=("paths",))

    def _open_settings_logging(self):
        self._exec_settings_dialog(visible_sections=("logging",))

    def _open_settings_log_cleanup(self):
        self._exec_settings_dialog(visible_sections=("log_cleanup",))

    def _open_settings_tools(self):
        self._exec_settings_dialog(visible_sections=("tools",))

    def _open_settings_defaults(self):
        self._exec_settings_dialog(visible_sections=("defaults",))

    def _open_settings_parallel(self):
        self._exec_settings_dialog(visible_sections=("parallel",))

    def _open_settings_media_library(self):
        self._exec_settings_dialog(visible_sections=("media_library",))

    def _open_settings_postprocess(self):
        self._exec_settings_dialog(visible_sections=("postprocess",))

    def _open_settings_source_visual(self):
        self._exec_settings_dialog(visible_sections=("source_visual",))

    def _open_settings_containers(self):
        self._exec_settings_dialog(visible_sections=("containers",))

    def _open_settings_autocrop(self):
        self._exec_settings_dialog(visible_sections=("autocrop",))

    def _open_settings_imax(self):
        self._exec_settings_dialog(visible_sections=("imax",))

    def _open_settings_validation(self):
        self._exec_settings_dialog(visible_sections=("validation",))

    def _open_settings_save(self):
        from .save_settings_dialog import SaveSettingsDialog
        dlg = SaveSettingsDialog(self)
        if dlg.exec():
            self._reload_all_paths()
            self.statusBar().showMessage("Einstellungen gespeichert.", 3000)

    def _open_settings_move_conflict(self):
        self._exec_settings_dialog(visible_sections=("move_conflict",))

    def _open_timeout_settings(self):
        from .timeout_settings_dialog import TimeoutSettingsDialog
        dlg = TimeoutSettingsDialog(self)
        if dlg.exec():
            self.statusBar().showMessage("Timeout-Einstellungen gespeichert.", 3000)

    def _exec_rules_dialog(
        self,
        *,
        visible_tabs: tuple[str, ...] | None = None,
        initial_tab: str | None = None,
        window_title: str | None = None,
    ):
        from .rules_dialog import RulesDialog
        RulesDialog(
            self,
            visible_tabs=visible_tabs,
            initial_tab=initial_tab,
            window_title=window_title,
        ).exec()

    def _open_rules(self):
        self._exec_rules_dialog()

    def _open_rules_series(self):
        self._exec_rules_dialog(visible_tabs=("series",), initial_tab="series")

    def _open_rules_renamer(self):
        self._exec_rules_dialog(visible_tabs=("renamer",), initial_tab="renamer")

    def _open_rules_audio(self):
        self._exec_rules_dialog(visible_tabs=("audio",), initial_tab="audio")

    def _open_rules_subtitles(self):
        self._exec_rules_dialog(visible_tabs=("subtitles",), initial_tab="subtitles")

    def _open_rules_flags(self):
        self._exec_rules_dialog(visible_tabs=("flags",), initial_tab="flags")

    def _open_online_metadata_settings(self):
        from .online_metadata_dialog import OnlineMetadataDialog

        dlg = OnlineMetadataDialog(self)
        if dlg.exec():
            self.statusBar().showMessage("Online-Metadaten gespeichert.", 3000)

    def _open_media_library(self, initial_tab: str = "status"):
        from .media_library_dialog import MediaLibraryDialog

        dlg = MediaLibraryDialog(self, initial_tab=initial_tab)
        dlg.exec()

    def _reload_all_paths(self):
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if hasattr(w, "reload_paths"):
                w.reload_paths()
