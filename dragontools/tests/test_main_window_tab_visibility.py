from __future__ import annotations

import types

import pytest

pytest.importorskip("PyQt6")
from types import SimpleNamespace


class _Settings:
    def __init__(self):
        self.values = {}
        self.synced = False

    def setValue(self, key, value):
        self.values[key] = value

    def sync(self):
        self.synced = True


class _Action:
    def __init__(self):
        self.checked = None
        self.blocked = False

    def blockSignals(self, blocked):
        previous = self.blocked
        self.blocked = bool(blocked)
        return previous

    def setChecked(self, checked):
        self.checked = bool(checked)


class _TabBar:
    def __init__(self, keys):
        self.keys = list(keys)

    def tabData(self, index):
        return self.keys[index]

    def setTabData(self, index, key):
        self.keys[index] = key


class _Tabs:
    def __init__(self, keys):
        self._bar = _TabBar(keys)
        self.current_index = None

    def count(self):
        return len(self._bar.keys)

    def tabBar(self):
        return self._bar

    def removeTab(self, index):
        self._bar.keys.pop(index)

    def insertTab(self, index, _widget, _label):
        self._bar.keys.insert(index, None)
        return index

    def setCurrentIndex(self, index):
        self.current_index = index


def _fake_window(keys):
    from dragontools.gui.main_window import MainWindow

    window = SimpleNamespace(
        _settings=_Settings(),
        _tab_actions={"av1": _Action()},
        _closed_tabs=[],
        _tab_widgets={"av1": object()},
        tabs=_Tabs(keys),
    )
    window._set_tab_visible_setting = types.MethodType(MainWindow._set_tab_visible_setting, window)
    window._tab_label = types.MethodType(MainWindow._tab_label, window)
    window._reopen_tab = types.MethodType(MainWindow._reopen_tab, window)
    return window


def test_closing_tab_persists_hidden_state():
    from dragontools.gui.main_window import MainWindow

    window = _fake_window(["h265", "av1"])

    MainWindow._on_tab_close(window, 1)

    assert window.tabs.tabBar().keys == ["h265"]
    assert window._closed_tabs == [("av1", 1)]
    assert window._settings.values["tabs/visible/av1"] is False
    assert window._settings.synced is True
    assert window._tab_actions["av1"].checked is False
    assert window._tab_actions["av1"].blocked is False


def test_reopening_last_tab_persists_visible_state():
    from dragontools.gui.main_window import MainWindow

    window = _fake_window(["h265"])
    window._closed_tabs.append(("av1", 1))

    MainWindow._reopen_last_tab(window)

    assert window.tabs.tabBar().keys == ["h265", "av1"]
    assert window.tabs.current_index == 1
    assert window._settings.values["tabs/visible/av1"] is True
    assert window._tab_actions["av1"].checked is True
