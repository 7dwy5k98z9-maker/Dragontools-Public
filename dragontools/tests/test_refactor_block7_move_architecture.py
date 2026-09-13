from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _class(rel: str, name: str) -> ast.ClassDef:
    tree = ast.parse(_source(rel))
    return next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)


def test_move_thread_is_a_small_qt_facade():
    source = _source("worker/move_thread.py")
    node = _class("worker/move_thread.py", "MoveThread")
    methods = {
        child.name
        for child in node.body
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert len(source.splitlines()) < 180
    assert methods == {"__init__", "run"}
    assert "MoveRuntimeControlMixin" in source
    assert "MoveResultCommitMixin" in source
    assert "MoveBatchLifecycleMixin" in source


def test_move_runtime_control_is_qt_independent():
    source = _source("worker/move_runtime_control.py")
    assert "PyQt6" not in source
    assert len(source.splitlines()) < 100
    for name in ("provide_decision", "request_abort", "pause", "resume", "_ask"):
        assert name in source


def test_move_commit_and_lifecycle_are_bounded():
    commit = _source("worker/move_result_commit.py")
    lifecycle = _source("worker/move_batch_lifecycle.py")

    assert len(commit.splitlines()) < 190
    assert len(lifecycle.splitlines()) < 130
    assert "MoveFileService" in commit
    assert "record_media_library_move" in commit
    assert "MoveJournal.start" in lifecycle
    assert "MoveBatchExecutor" in lifecycle


def test_move_thread_keeps_destructive_operations_outside_facade():
    source = _source("worker/move_thread.py")
    forbidden = ("shutil.move", "shutil.rmtree", "os.link(", "os.replace(")
    assert not any(token in source for token in forbidden)


def test_release_smoke_tracks_block7_modules():
    source = _source("core/release_validation_smoke_modules.py")
    for name in (
        "move_runtime_control",
        "move_result_commit",
        "move_batch_lifecycle",
    ):
        assert name in source
