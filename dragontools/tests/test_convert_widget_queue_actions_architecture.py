from __future__ import annotations

import ast
from pathlib import Path


GUI_DIR = Path(__file__).resolve().parents[1] / "gui"


def _module(name: str) -> tuple[Path, ast.Module]:
    path = GUI_DIR / name
    return path, ast.parse(path.read_text(encoding="utf-8"))


def _class(tree: ast.Module, name: str) -> ast.ClassDef:
    return next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)


def test_queue_actions_facade_contains_no_business_methods():
    path, tree = _module("convert_widget_queue_actions.py")
    facade = _class(tree, "ConvertWidgetQueueActionsMixin")

    assert len(path.read_text(encoding="utf-8").splitlines()) <= 60
    methods = [node.name for node in facade.body if isinstance(node, ast.FunctionDef)]
    assert methods == []

    bases = {
        base.id
        for base in facade.bases
        if isinstance(base, ast.Name)
    }
    assert bases == {
        "ConvertWidgetQueueDragDropMixin",
        "ConvertWidgetQueueManagementMixin",
        "ConvertWidgetQueueWindowActionsMixin",
        "ConvertWidgetQueueContextActionsMixin",
        "ConvertWidgetQueueOverrideActionsMixin",
        "ConvertWidgetQueueBadgesMixin",
        "ConvertWidgetSourceVisualActionsMixin",
    }


def test_queue_action_collaborators_are_bounded_and_single_owner():
    limits = {
        "convert_widget_queue_dragdrop.py": 100,
        "convert_widget_queue_management.py": 90,
        "convert_widget_queue_window_actions.py": 100,
        "convert_widget_queue_context_actions.py": 190,
        "convert_widget_queue_override_actions.py": 190,
        "convert_widget_queue_badges.py": 140,
        "convert_widget_source_visual_actions.py": 120,
    }
    owners: dict[str, str] = {}
    for filename, maximum in limits.items():
        path, tree = _module(filename)
        assert len(path.read_text(encoding="utf-8").splitlines()) <= maximum, filename
        classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
        assert len(classes) == 1, filename
        for method in classes[0].body:
            if not isinstance(method, ast.FunctionDef):
                continue
            assert method.name not in owners, f"{method.name} duplicated in {filename} and {owners[method.name]}"
            owners[method.name] = filename

    assert len(owners) == 39


def test_queue_action_mixins_keep_unique_aggregation_surface():
    expected = {
        "_collect_video_paths_from_urls",
        "dragEnterEvent",
        "dragMoveEvent",
        "eventFilter",
        "dropEvent",
        "add_dropped_files",
        "_add_files",
        "_add_folder",
        "_sync_queue_order",
        "_remove_path",
        "_remove_paths",
        "remove_selected_files",
        "_clear",
        "_requeue_paths",
        "open_queue_window",
        "_refresh_queue_window",
        "_apply_queue_window_order",
        "_ctx_menu",
        "_terminate_current_ffmpeg_for_path",
        "_show_media_info",
        "_show_rule_test",
        "show_batch_rule_test",
        "_encoder_profile_choices",
        "_assign_encoder_profile",
        "_toggle_strip_only",
        "_toggle_imax",
        "_edit_override",
        "update_queue_label",
        "_override_label_tags",
        "_processing_badges",
        "_encode_badge_label",
        "_cached_preflight_preview",
        "_postprocess_enabled_for_badge",
        "_postprocess_badge_parts",
        "_source_visual_settings_for_manual_check",
        "_show_source_visual_check",
        "_allow_suspicious_source",
        "_override_label_text",
        "_set_file_list_item_text",
    }

    found: set[str] = set()
    for filename in (
        "convert_widget_queue_dragdrop.py",
        "convert_widget_queue_management.py",
        "convert_widget_queue_window_actions.py",
        "convert_widget_queue_context_actions.py",
        "convert_widget_queue_override_actions.py",
        "convert_widget_queue_badges.py",
        "convert_widget_source_visual_actions.py",
    ):
        _, tree = _module(filename)
        for cls in (node for node in tree.body if isinstance(node, ast.ClassDef)):
            found.update(
                node.name
                for node in cls.body
                if isinstance(node, ast.FunctionDef)
            )

    assert found == expected


def test_source_visual_and_profile_dependencies_have_dedicated_owners():
    dependency_owners: dict[str, set[str]] = {
        "SourceVisualCheckService": set(),
        "profile_to_override": set(),
        "MediaInfoDialog": set(),
    }
    for path in GUI_DIR.glob("convert_widget_queue_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in dependency_owners:
                dependency_owners[node.id].add(path.name)
    source_visual_path = GUI_DIR / "convert_widget_source_visual_actions.py"
    source_tree = ast.parse(source_visual_path.read_text(encoding="utf-8"))
    if any(isinstance(node, ast.Name) and node.id == "SourceVisualCheckService" for node in ast.walk(source_tree)):
        dependency_owners["SourceVisualCheckService"].add(source_visual_path.name)

    assert dependency_owners["SourceVisualCheckService"] == {"convert_widget_source_visual_actions.py"}
    assert dependency_owners["profile_to_override"] == {"convert_widget_queue_override_actions.py"}
    assert dependency_owners["MediaInfoDialog"] == {"convert_widget_queue_context_actions.py"}


def test_convert_widget_remove_signal_targets_existing_queue_api():
    composition_path = GUI_DIR / "convert_widget_composition.py"
    composition_source = composition_path.read_text(encoding="utf-8")
    _, queue_tree = _module("convert_widget_queue_management.py")
    queue_cls = _class(queue_tree, "ConvertWidgetQueueManagementMixin")
    queue_methods = {node.name for node in queue_cls.body if isinstance(node, ast.FunctionDef)}
    assert "owner.file_list.remove_requested.connect(owner._remove_paths)" in composition_source
    assert "remove_selected_files_paths" not in composition_source
    assert "_remove_paths" in queue_methods
