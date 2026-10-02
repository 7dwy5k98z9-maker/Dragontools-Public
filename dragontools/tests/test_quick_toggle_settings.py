from __future__ import annotations


class FakeSettings:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.synced = 0

    def value(self, key, default=None, **_kwargs):
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.values[key] = value

    def sync(self):
        self.synced += 1


def test_quick_toggle_contract_uses_existing_global_setting_keys():
    from dragontools.core.settings_conversion import (
        SET_KEY_HDR10PLUS_GENERATOR_ENABLED,
        SET_KEY_QUALITY_TARGET_ENABLED,
        SET_KEY_SDR_HDR_ENABLED,
    )
    from dragontools.core.settings_watch import SET_KEY_WATCH_ENABLED
    from dragontools.gui.convert_widget_quick_settings import QUICK_TOGGLE_SPECS

    by_attr = {spec.attr_name: spec for spec in QUICK_TOGGLE_SPECS}
    assert by_attr["hdr10plus_generator_quick_cb"].key == SET_KEY_HDR10PLUS_GENERATOR_ENABLED
    assert by_attr["sdr_hdr_quick_cb"].key == SET_KEY_SDR_HDR_ENABLED
    assert by_attr["watch_folder_quick_cb"].key == SET_KEY_WATCH_ENABLED
    assert by_attr["quality_target_quick_cb"].key == SET_KEY_QUALITY_TARGET_ENABLED
    assert by_attr["forced_burn_quick_cb"].rule_group == "burn_in_rules"
    assert by_attr["forced_burn_quick_cb"].key == "auto_burn_forced"
    assert by_attr["subtitle_external_quick_cb"].key == "additional_sidecars_enabled"


def test_quick_toggle_write_is_persistent_and_roundtrips():
    from dragontools.gui.convert_widget_quick_settings import (
        QUICK_TOGGLE_SPECS,
        quick_toggle_value,
        set_quick_toggle_value,
    )

    settings = FakeSettings()
    for spec in (s for s in QUICK_TOGGLE_SPECS if not s.subtitle_rule):
        set_quick_toggle_value(settings, spec, True)
        assert quick_toggle_value(settings, spec) is True
        set_quick_toggle_value(settings, spec, False)
        assert quick_toggle_value(settings, spec) is False
    assert settings.synced == 2 * sum(not s.subtitle_rule for s in QUICK_TOGGLE_SPECS)


def test_subtitle_quick_toggles_update_existing_rules(monkeypatch):
    from dragontools.gui import rules_dialog_storage
    from dragontools.gui.convert_widget_quick_settings import (
        QUICK_TOGGLE_SPECS, quick_toggle_value, set_quick_toggle_value,
    )
    rules = {
        "keep_rules": {"keep_regular": True}, "pgs_original_storage": "internal_mkv",
        "burn_in_rules": {"burn_language": "en", "ask_if_ambiguous": False},
    }
    saved = []
    monkeypatch.setattr(rules_dialog_storage, "_load", lambda name: dict(rules))
    monkeypatch.setattr(rules_dialog_storage, "_save", lambda name, value: (saved.append(name), rules.update(value)))
    settings = FakeSettings()
    specs = [s for s in QUICK_TOGGLE_SPECS if s.subtitle_rule]
    assert {s.key for s in specs} == {
        "pgs_to_srt_enabled", "text_to_srt_sidecar_enabled",
        "additional_sidecars_enabled", "auto_burn_forced",
    }
    for spec in specs:
        assert quick_toggle_value(settings, spec) == spec.default
        set_quick_toggle_value(settings, spec, True)
        assert quick_toggle_value(settings, spec)
        set_quick_toggle_value(settings, spec, False)
        assert not quick_toggle_value(settings, spec)
    assert rules["keep_rules"] == {"keep_regular": True}
    assert rules["pgs_original_storage"] == "internal_mkv"
    assert rules["burn_in_rules"] == {
        "burn_language": "en", "ask_if_ambiguous": False, "auto_burn_forced": False,
    }
    assert "auto_burn_forced" not in rules
    assert saved == ["subtitle_rules"] * (2 * len(specs))
    assert settings.values == {}


def test_quick_toggles_are_rendered_next_to_queue_arrows():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "gui" / "convert_widget_layout_runtime.py").read_text(
        encoding="utf-8"
    )
    stretch_pos = source.index("quick_row.addStretch(1)")
    toggle_pos = source.index("for spec in QUICK_TOGGLE_SPECS")
    layout_pos = source.index("ll.addLayout(order_row)")
    assert stretch_pos < toggle_pos < layout_pos
    assert "extra_toggle_row" not in source
    assert "order_row.addWidget(quick_scroll, 1)" in source
