from __future__ import annotations

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QMainWindow

from dragontools.gui import main_window_tabs


@pytest.mark.parametrize("all_hidden", [False, True])
def test_tabs_initialize_before_visibility_guard(qtbot, tmp_path, monkeypatch, all_hidden):
    class Window(main_window_tabs.MainWindowTabsMixin, QMainWindow):
        def __init__(self):
            super().__init__()
            self._settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
            self._settings.setValue("defaults/codec", "h264")
            self._tab_widgets = {}
            self._closed_tabs = []

        def _ensure_tab_loaded(self, _idx):
            pass

    keys = ("h265", "h264", "av1", "iso", "merge", "mp4_remux", "audio_muxer",
            "audio_video_matcher", "subtitle", "movie_renamer", "quality_tester")
    monkeypatch.setattr(main_window_tabs, "get_visible_tabs", lambda: {key: not all_hidden for key in keys})
    window = Window()
    qtbot.addWidget(window)
    window._init_tabs()

    assert window.tabs.count() == (1 if all_hidden else len(keys))
    assert window.tabs.tabBar().tabData(window.tabs.currentIndex()) == "h264"
    if all_hidden:
        assert window._settings.value("tabs/visible/h264", type=bool) is True
