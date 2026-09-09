from __future__ import annotations

import importlib.util

import pytest


HAS_QT_TEST_RUNTIME = (
    importlib.util.find_spec("PyQt6") is not None
    and importlib.util.find_spec("pytestqt") is not None
)


class DummySettings:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def value(self, key, default=None, type=None):
        value = self.values.get(key, default)
        if type is int:
            return int(value)
        if type is float:
            return float(value)
        if type is str:
            return str(value)
        return value

    def contains(self, key):
        return key in self.values

    def setValue(self, key, value):
        self.values[key] = value

    def sync(self):
        return None


def test_settings_bool_parses_string_values_without_python_bool_trap():
    from dragontools.core.settings import settings_bool

    settings = DummySettings({
        "a": "false",
        "b": "0",
        "c": "off",
        "d": "true",
        "e": 1,
    })

    assert settings_bool(settings, "a", True) is False
    assert settings_bool(settings, "b", True) is False
    assert settings_bool(settings, "c", True) is False
    assert settings_bool(settings, "d", False) is True
    assert settings_bool(settings, "e", False) is True
    assert settings_bool(None, "missing", True) is True


def test_ui_section_expanded_key_is_stable_and_namespaced():
    from dragontools.core.settings import ui_section_expanded_key

    assert (
        ui_section_expanded_key("convert/encoder options")
        == "ui/sections/convert/encoder_options/expanded"
    )
    assert ui_section_expanded_key("") == "ui/sections/default/expanded"


@pytest.mark.skipif(
    not HAS_QT_TEST_RUNTIME,
    reason="PyQt6 + pytest-qt werden fuer den echten Widget-Lifecycle benoetigt",
)
def test_collapsible_groupbox_persists_user_click(qtbot):
    from dragontools.core.settings import ui_section_expanded_key
    from dragontools.gui.convert_widget_layout import CollapsibleGroupBox

    settings = DummySettings()
    first = CollapsibleGroupBox(
        "Testbereich",
        collapsed=False,
        settings=settings,
        section_id="convert/test",
    )
    qtbot.addWidget(first)

    first.toggle_btn.click()

    key = ui_section_expanded_key("convert/test")
    assert settings.values[key] is False
    second = CollapsibleGroupBox(
        "Testbereich",
        collapsed=False,
        settings=settings,
        section_id="convert/test",
    )
    qtbot.addWidget(second)
    assert second.toggle_btn.isChecked() is False


def test_settings_int_float_and_text_clamp_or_fallback():
    from dragontools.core.settings import settings_float, settings_int, settings_text

    settings = DummySettings({
        "int_low": "-5",
        "int_high": "999",
        "float_bad": "x",
        "text": "bad",
    })

    assert settings_int(settings, "int_low", 3, minimum=1, maximum=10) == 1
    assert settings_int(settings, "int_high", 3, minimum=1, maximum=10) == 10
    assert settings_float(settings, "float_bad", 1.5, minimum=0.0, maximum=4.0) == 1.5
    assert settings_text(settings, "text", "good", allowed={"good", "better"}) == "good"


def test_postprocess_config_uses_centralized_settings_limits():
    from dragontools.core.settings import (
        DEFAULT_TRICKPLAY_HWACCEL,
        SET_KEY_NFO_CONFLICT_MODE,
        SET_KEY_TRICKPLAY_HWACCEL,
        SET_KEY_TRICKPLAY_MAX_JOBS,
        SET_KEY_TRICKPLAY_QSCALE,
        SET_KEY_TRICKPLAY_SOURCE_MODE,
    )
    from dragontools.worker.postprocess_service import config_from_settings

    cfg = config_from_settings(DummySettings({
        SET_KEY_NFO_CONFLICT_MODE: "invalid",
        SET_KEY_TRICKPLAY_SOURCE_MODE: "invalid",
        SET_KEY_TRICKPLAY_HWACCEL: "invalid",
        SET_KEY_TRICKPLAY_QSCALE: 99,
        SET_KEY_TRICKPLAY_MAX_JOBS: 99,
    }))

    assert cfg.nfo.conflict_mode == "skip"
    assert cfg.trickplay.source_mode == "output"
    assert cfg.trickplay.hwaccel == DEFAULT_TRICKPLAY_HWACCEL
    assert cfg.trickplay.qscale == 31
    assert cfg.trickplay.max_jobs == 8


def test_output_size_policy_accepts_injected_settings(tmp_path):
    from dragontools.core.settings import (
        SET_KEY_SAVE_ALLOW_LARGER_OUTPUT,
        SET_KEY_SAVE_ALLOW_LARGER_OUTPUT_PERCENT,
    )
    from dragontools.worker.output_size_policy import validate_output_size_policy

    source = tmp_path / "source.mkv"
    output = tmp_path / "output.mkv"
    source.write_bytes(b"1" * 100)
    output.write_bytes(b"2" * 150)
    messages = []

    ok, preserved = validate_output_size_policy(
        source,
        output,
        logger=lambda msg, _level="warn": messages.append(msg),
        settings=DummySettings({
            SET_KEY_SAVE_ALLOW_LARGER_OUTPUT: True,
            SET_KEY_SAVE_ALLOW_LARGER_OUTPUT_PERCENT: 10,
        }),
    )

    assert ok is False
    assert preserved is not None
    assert preserved.exists()
    assert any("größer als erlaubt" in msg for msg in messages)


def test_type_utils_handle_legacy_float_strings_and_unknown_bool_safely():
    from dragontools.core.type_utils import _safe_bool, _safe_float, _safe_int

    assert _safe_int("23.0") == 23
    assert _safe_int("4,0") == 4
    assert _safe_float("1,5") == 1.5
    assert _safe_bool("false", True) is False
    assert _safe_bool("0", True) is False
    assert _safe_bool("true", False) is True
    assert _safe_bool("unexpected", False) is False
    assert _safe_bool("unexpected", True) is True


def test_settings_int_accepts_qsettings_float_string():
    from dragontools.core.settings import settings_int

    settings = DummySettings({"legacy": "32.0"})
    assert settings_int(settings, "legacy", 7) == 32
