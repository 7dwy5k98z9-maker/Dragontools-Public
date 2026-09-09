# -*- coding: utf-8 -*-
from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
WORKER = PACKAGE / "worker"


def _class(path: Path, name: str) -> ast.ClassDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)


def test_parallel_converter_thread_ist_koordination_statt_god_class():
    path = WORKER / "parallel_converter_thread.py"
    cls = _class(path, "ParallelConverterThread")
    methods = [node for node in cls.body if isinstance(node, ast.FunctionDef)]
    assert cls.end_lineno - cls.lineno + 1 <= 420
    assert max(node.end_lineno - node.lineno + 1 for node in methods) <= 60
    assert "ParallelWorkerLauncher" in path.read_text(encoding="utf-8")
    assert "ParallelChildResultCoordinator" in path.read_text(encoding="utf-8")


def test_parallel_converter_helpers_bleiben_qt_unabhaengig():
    for filename in (
        "parallel_converter_compat.py",
        "parallel_worker_launcher.py",
        "parallel_child_result_coordinator.py",
        "parallel_converter_state.py",
    ):
        source = (WORKER / filename).read_text(encoding="utf-8")
        assert "PyQt6" not in source
        assert "PySide" not in source
        assert "subprocess" not in source
