from __future__ import annotations

import ast
from pathlib import Path


GUI_DIR = Path(__file__).resolve().parents[1] / "gui"


def _module(name: str) -> tuple[Path, ast.Module]:
    path = GUI_DIR / name
    return path, ast.parse(path.read_text(encoding="utf-8"))


def _class(tree: ast.Module, name: str) -> ast.ClassDef:
    return next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)


def test_movie_renamer_widget_is_thin_orchestrator():
    path, tree = _module("movie_renamer_widget.py")
    widget = _class(tree, "MovieRenamerWidget")

    assert widget.end_lineno - widget.lineno + 1 <= 240
    assert len(path.read_text(encoding="utf-8").splitlines()) <= 270

    forbidden_calls = {
        "rename_movie_file",
        "build_rename_proposal",
        "parse_movie_release_name",
        "parse_series_release_name",
        "build_target_filename",
        "build_series_target_filename",
        "client_from_config",
        "config_from_settings",
    }
    called = {
        node.func.id
        for node in ast.walk(widget)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert not (called & forbidden_calls)


def test_movie_renamer_collaborators_are_bounded():
    limits = {
        "movie_renamer_view.py": 220,
        "movie_renamer_table_controller.py": 340,
        "movie_renamer_resolver.py": 190,
        "movie_renamer_actions.py": 200,
    }
    for filename, maximum in limits.items():
        path = GUI_DIR / filename
        assert path.exists(), filename
        assert len(path.read_text(encoding="utf-8").splitlines()) <= maximum, filename


def test_movie_renamer_widget_exposes_only_user_actions_and_lifecycle():
    _, tree = _module("movie_renamer_widget.py")
    widget = _class(tree, "MovieRenamerWidget")
    methods = {
        node.name
        for node in widget.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    public_actions = {
        "add_paths",
        "resolve_proposals",
        "accept_selected",
        "accept_safe",
        "reject_selected",
        "execute_rename",
        "remove_selected",
        "clear",
        "closeEvent",
    }
    assert public_actions <= methods
    obsolete_delegates = {
        "_resolve_new_proposals", "_start_resolve_jobs", "_choose_files",
        "_choose_folder", "_add_row", "_on_proposal_ready",
        "_install_candidate_combo", "_on_candidate_combo_changed",
        "_apply_candidate", "_collect_rename_problems", "_known_path_keys",
        "_selected_rows", "_row_item", "_set_item", "_set_status",
        "_row_meta", "_row_path", "_set_row_path", "_row_proposal",
        "_set_row_proposal", "_row_accepted", "_set_row_accepted",
        "_target_name", "_set_busy",
    }
    assert not (methods & obsolete_delegates)


def test_filesystem_rename_is_owned_by_action_controller_only():
    owners = []
    for path in GUI_DIR.glob("movie_renamer*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "rename_movie_file"
            for node in ast.walk(tree)
        ):
            owners.append(path.name)
    assert owners == ["movie_renamer_actions.py"]


def test_metadata_worker_is_not_owned_by_main_widget():
    _, tree = _module("movie_renamer_widget.py")
    widget = _class(tree, "MovieRenamerWidget")
    assert not any(isinstance(node, ast.ClassDef) for node in widget.body)

    resolver_path, resolver_tree = _module("movie_renamer_resolver.py")
    assert resolver_path.exists()
    assert any(
        isinstance(node, ast.ClassDef) and node.name == "MovieRenameResolveThread"
        for node in resolver_tree.body
    )
