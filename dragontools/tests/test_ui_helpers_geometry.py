from __future__ import annotations

import importlib.util

import pytest


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("PyQt6") is None,
    reason="PyQt6 wird fuer die UI-Helper-Geometrietests benoetigt",
)

class _Settings:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.synced = False

    def value(self, key, default=None, type=None):
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.values[key] = value

    def sync(self):
        self.synced = True


class _Signal:
    def __init__(self):
        self._slots = []

    def connect(self, slot):
        self._slots.append(slot)

    def emit(self, *args):
        for slot in list(self._slots):
            slot(*args)


class _Widget:
    def __init__(self):
        self.finished = _Signal()
        self.restored = None

    def restoreGeometry(self, geometry):
        self.restored = geometry
        return True

    def saveGeometry(self):
        return b"geometry"


def test_window_geometry_key_is_stable_and_namespaced():
    from dragontools.gui.ui_helpers import window_geometry_key

    assert window_geometry_key("settings_dialog/timeouts") == "windows/settings_dialog/timeouts/geometry"
    assert window_geometry_key(" file override ") == "windows/file_override/geometry"
    assert window_geometry_key("") == "windows/default/geometry"


def test_restore_and_save_window_geometry_use_same_key():
    from dragontools.gui.ui_helpers import (
        restore_window_geometry,
        save_window_geometry,
        window_geometry_key,
    )

    key = window_geometry_key("media_info_dialog")
    settings = _Settings({key: b"old-geometry"})
    widget = _Widget()

    restore_window_geometry(widget, "media_info_dialog", settings)
    save_window_geometry(widget, "media_info_dialog", settings)

    assert widget.restored == b"old-geometry"
    assert settings.values[key] == b"geometry"
    assert settings.synced is True


def test_install_persistent_window_geometry_saves_when_dialog_finishes():
    from dragontools.gui.ui_helpers import install_persistent_window_geometry, window_geometry_key

    widget = _Widget()
    settings = _Settings()

    install_persistent_window_geometry(widget, "preflight_dialog", settings)
    widget.finished.emit(0)

    assert settings.values[window_geometry_key("preflight_dialog")] == b"geometry"
    assert settings.synced is True
