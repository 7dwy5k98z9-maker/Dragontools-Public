from __future__ import annotations

import ast
from pathlib import Path


GUI_DIR = Path(__file__).resolve().parents[1] / "gui"

EXPECTED_METHODS = {
    "build_nvenc_panel",
    "build_qsv_panel",
    "build_amf_panel",
    "build_x265_panel",
    "bind_main_widgets",
    "enc_key",
    "refresh_enc_panel",
    "detect_encoders",
    "_active_encoder",
    "collect_enc_opts",
    "connect_encoder_settings_signals",
    "_sync_state_from_ui",
    "save_encoder_settings",
    "load_encoder_settings",
    "save_profile",
    "apply_profile_to_ui",
    "apply_assistant_profile",
    "load_profile",
    "reset_to_defaults",
    "_apply_encoder_combo_value",
    "_combo_value",
    "_apply_int_value",
    "_apply_float_value",
    "_imax_probe_interval_s",
    "_settings_int",
    "_settings_text",
}

IMPLEMENTATION_FILES = (
    "encoder_settings_panels.py",
    "encoder_settings_options.py",
    "encoder_settings_persistence.py",
    "encoder_settings_profiles.py",
)


def _classes(path: Path) -> list[ast.ClassDef]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [node for node in tree.body if isinstance(node, ast.ClassDef)]


def _method_names(path: Path) -> set[str]:
    names: set[str] = set()
    for cls in _classes(path):
        names.update(
            node.name
            for node in cls.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
    return names


def test_encoder_settings_controller_is_small_composition_facade():
    path = GUI_DIR / "encoder_settings_controller.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "EncoderSettingsController")
    methods = [node for node in cls.body if isinstance(node, ast.FunctionDef)]

    assert path.read_text(encoding="utf-8").count("\n") + 1 <= 80
    assert [method.name for method in methods] == ["__init__"]
    assert cls.end_lineno - cls.lineno + 1 <= 45


def test_encoder_settings_methods_have_exactly_one_implementation_owner():
    owners: dict[str, list[str]] = {name: [] for name in EXPECTED_METHODS}
    for filename in IMPLEMENTATION_FILES:
        for name in _method_names(GUI_DIR / filename):
            if name in owners:
                owners[name].append(filename)

    assert set(owners) == EXPECTED_METHODS
    assert all(len(files) == 1 for files in owners.values()), owners


def test_encoder_settings_modules_remain_focused():
    limits = {
        "encoder_settings_panels.py": 130,
        "encoder_settings_options.py": 175,
        "encoder_settings_persistence.py": 185,
        "encoder_settings_profiles.py": 180,
    }
    for filename, max_lines in limits.items():
        path = GUI_DIR / filename
        lines = path.read_text(encoding="utf-8").count("\n") + 1
        assert lines <= max_lines, f"{filename} grew to {lines} lines"


def test_encoder_settings_persistence_and_profiles_are_separated():
    persistence = (GUI_DIR / "encoder_settings_persistence.py").read_text(encoding="utf-8")
    profiles = (GUI_DIR / "encoder_settings_profiles.py").read_text(encoding="utf-8")
    panels = (GUI_DIR / "encoder_settings_panels.py").read_text(encoding="utf-8")

    assert "save_profile_dialog" not in persistence
    assert "assistant_profile_dialog" not in persistence
    assert "self._settings.setValue" not in profiles
    assert "encoder/{c}/" not in profiles
    assert "encoder_combo.currentIndex()" not in profiles
    assert "SET_KEY_" not in panels
