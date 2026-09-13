from __future__ import annotations

import ast
from pathlib import Path

from dragontools.gui.online_metadata_settings_state import (
    OnlineMetadataSettingsState,
    load_online_metadata_settings,
    save_online_metadata_settings,
)

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
GUI_ROOT = PACKAGE_ROOT / "gui"


class _FakeSettings:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.synced = 0

    def value(self, key, defaultValue=None, *, type=None):
        value = self.values.get(key, defaultValue)
        if type is None:
            return value
        if type is bool:
            return bool(value)
        return type(value)

    def setValue(self, key, value):
        self.values[key] = value

    def sync(self):
        self.synced += 1


def _class_methods(path: Path, class_name: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    return {node.name for node in cls.body if isinstance(node, ast.FunctionDef)}


def test_block12_facades_stay_small() -> None:
    assert len((GUI_ROOT / "audio_video_matcher_widget.py").read_text(encoding="utf-8").splitlines()) <= 60
    assert len((GUI_ROOT / "online_metadata_dialog.py").read_text(encoding="utf-8").splitlines()) <= 60


def test_block12_matcher_keeps_explicit_shutdown_contract() -> None:
    methods = _class_methods(GUI_ROOT / "audio_video_matcher_widget.py", "AudioVideoMatcherWidget")
    assert "iter_shutdown_workers" in methods


def test_block12_split_modules_are_release_smoke_checked() -> None:
    from dragontools.core.release_validation_package import _SMOKE_MODULES

    checked = {path.as_posix() for path in _SMOKE_MODULES}
    expected = {
        "gui/audio_video_matcher_view.py",
        "gui/audio_video_matcher_paths.py",
        "gui/audio_video_matcher_runtime.py",
        "gui/audio_video_matcher_results.py",
        "gui/online_metadata_dialog_view.py",
        "gui/online_metadata_dialog_state.py",
        "gui/online_metadata_settings_state.py",
    }
    assert expected <= checked


def test_block12_metadata_settings_roundtrip_is_lossless() -> None:
    state = OnlineMetadataSettingsState(
        movie_provider="both",
        series_provider="thetvdb",
        movie_preferred_provider="thetvdb",
        series_preferred_provider="tmdb",
        tmdb_enabled=True,
        tmdb_read_token="read-token",
        tmdb_api_key="tmdb-key",
        tvdb_enabled=True,
        tvdb_api_key="tvdb-key",
        tvdb_pin="1234",
        tvdb_bearer_token="bearer",
        language="de-DE",
        fallback_language="en-US",
        cache_enabled=False,
        cache_days=7,
    )
    settings = _FakeSettings()
    save_online_metadata_settings(settings, state)
    assert settings.synced == 1
    assert load_online_metadata_settings(settings) == state
