from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _class_node(rel: str, name: str) -> ast.ClassDef:
    tree = ast.parse(_source(rel))
    return next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)


def test_convert_file_queue_has_no_owner_private_backreference():
    source = _source("gui/convert_widget_file_queue.py")
    helper = _class_node("gui/convert_widget_file_queue.py", "ConvertWidgetFileQueueHelper")
    helper_source = "\n".join(source.splitlines()[helper.lineno - 1 : helper.end_lineno])

    assert "self.owner" not in helper_source
    assert "owner._" not in helper_source
    init = next(node for node in helper.body if isinstance(node, ast.FunctionDef) and node.name == "__init__")
    arg_names = {arg.arg for arg in init.args.args + init.args.kwonlyargs}
    assert {"parent_widget", "file_list", "state", "log"} <= arg_names


def test_convert_queue_window_uses_explicit_callbacks_not_owner_private_api():
    source = _source("gui/convert_queue_window.py")
    assert "self.owner" not in source
    assert "owner._" not in source
    window = _class_node("gui/convert_queue_window.py", "ConvertQueueWindow")
    init = next(node for node in window.body if isinstance(node, ast.FunctionDef) and node.name == "__init__")
    arg_names = {arg.arg for arg in init.args.args + init.args.kwonlyargs}
    assert {"source_list", "active_worker", "apply_queue_order", "toggle_pause", "abort"} <= arg_names


def test_parallel_converter_delegates_qt_independent_state():
    source = _source("worker/parallel_converter_thread.py")
    assert "ParallelQueueState" in source
    assert "ParallelWorkerRegistry" in source
    assert len(source.splitlines()) < 560

    state_source = _source("worker/parallel_converter_state.py")
    assert "PyQt6" not in state_source
    assert "class ParallelQueueState" in state_source
    assert "class ParallelResultState" in state_source
    assert "class ParallelWorkerRegistry" in state_source


def test_move_thread_drops_legacy_service_forwarders():
    source = _source("worker/move_thread.py")
    move_thread = _class_node("worker/move_thread.py", "MoveThread")
    method_names = {
        node.name for node in move_thread.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    forbidden = {
        "_new_move_result",
        "_resolve_rename_path",
        "_find_target_conflicts",
        "_format_conflicts",
        "_backup_conflicts_transactional",
        "_rollback_conflict_backups",
        "_discard_conflict_backups",
        "_resolve_directory_rename_path",
        "_move_directory",
        "_find_series_dir",
        "_handle_series",
        "_handle_film",
        "_move_trickplay_sidecar",
        "_sidecar_type",
        "_unique_trickplay_backup_path",
        "_sidecar_dest_name",
        "_is_film_target",
        "_record_replacement_reminder",
    }
    assert not (method_names & forbidden)
    assert len(source.splitlines()) < 480
