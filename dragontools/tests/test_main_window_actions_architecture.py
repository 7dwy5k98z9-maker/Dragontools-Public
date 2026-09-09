from __future__ import annotations

import ast
from pathlib import Path


GUI_DIR = Path(__file__).resolve().parents[1] / "gui"
FACADE = GUI_DIR / "main_window_actions.py"
ACTION_MODULES = (
    "main_window_backup_actions.py",
    "main_window_convert_actions.py",
    "main_window_help_actions.py",
    "main_window_metadata_actions.py",
    "main_window_profile_actions.py",
    "main_window_settings_actions.py",
    "main_window_system_actions.py",
)
EXPECTED_METHODS = {
    "_open_convert_queue",
    "_active_convert_widget",
    "_show_active_queue_rule_test",
    "_show_running_job_diagnostics",
    "_open_log_zoom_window",
    "_export_backup",
    "_restore_backup",
    "_exec_settings_dialog",
    "_open_settings",
    "_open_settings_paths",
    "_open_settings_logging",
    "_open_settings_log_cleanup",
    "_open_settings_tools",
    "_open_settings_defaults",
    "_open_settings_parallel",
    "_open_settings_media_library",
    "_open_settings_postprocess",
    "_open_settings_source_visual",
    "_open_settings_containers",
    "_open_settings_autocrop",
    "_open_settings_imax",
    "_open_settings_validation",
    "_open_settings_save",
    "_open_settings_move_conflict",
    "_open_timeout_settings",
    "_create_diagnostic_package",
    "_exec_rules_dialog",
    "_open_rules",
    "_open_rules_series",
    "_open_rules_renamer",
    "_open_rules_audio",
    "_open_rules_subtitles",
    "_open_rules_flags",
    "_open_online_metadata_settings",
    "_open_media_library",
    "_tmdb_client_or_warn",
    "_metadata_provider_label",
    "_test_tmdb_connection",
    "_search_online_metadata",
    "_clear_metadata_cache",
    "_open_help",
    "_find_handbook",
    "_open_handbook",
    "_open_shortcuts",
    "_open_changelog",
    "_open_legacy_changelog",
    "_diagnostic_tool_props",
    "_check_tools",
    "_check_tools_extended",
    "_check_release_build",
    "_launch_external",
    "_delete_selected_file",
    "_open_profile_manager",
    "_reset_defaults",
    "_toggle_dark",
    "_open_url",
    "_check_for_updates",
    "_check_for_updates_on_startup",
    "_handle_update_result",
    "_apply_default_profile",
    "_about",
    "_reload_all_paths",
}


def _classes(path: Path) -> list[ast.ClassDef]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [node for node in tree.body if isinstance(node, ast.ClassDef)]


def _methods(path: Path) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    result: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for cls in _classes(path):
        result.extend(
            node
            for node in cls.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
    return result


def test_actions_facade_contains_no_business_methods():
    classes = _classes(FACADE)
    facade = next(cls for cls in classes if cls.name == "MainWindowActionsMixin")
    methods = [
        node
        for node in facade.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert methods == []
    assert len(FACADE.read_text(encoding="utf-8").splitlines()) <= 40


def test_action_mixins_preserve_complete_aggregation_surface_without_duplicates():
    owners: dict[str, str] = {}
    for filename in ACTION_MODULES:
        path = GUI_DIR / filename
        assert path.is_file(), filename
        for method in _methods(path):
            assert method.name not in owners, (
                f"{method.name} ist doppelt in {owners[method.name]} und {filename} definiert"
            )
            owners[method.name] = filename

    assert set(owners) == EXPECTED_METHODS


def test_focused_action_modules_stay_small():
    for filename in ACTION_MODULES:
        path = GUI_DIR / filename
        lines = len(path.read_text(encoding="utf-8").splitlines())
        assert lines <= 260, f"{filename} ist mit {lines} Zeilen wieder zu groß"
        for method in _methods(path):
            length = (method.end_lineno or method.lineno) - method.lineno + 1
            assert length <= 130, f"{filename}:{method.name} ist mit {length} Zeilen zu groß"


def test_facade_only_composes_focused_action_mixins():
    tree = ast.parse(FACADE.read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert imports == {
        "annotations",
        "MainWindowBackupActionsMixin",
        "MainWindowConvertActionsMixin",
        "MainWindowHelpActionsMixin",
        "MainWindowMetadataActionsMixin",
        "MainWindowProfileActionsMixin",
        "MainWindowSettingsActionsMixin",
        "MainWindowSystemActionsMixin",
    }
