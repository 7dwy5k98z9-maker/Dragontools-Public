# -*- coding: utf-8 -*-
from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
WORKER_ROOT = PACKAGE_ROOT / "worker"


def _class_node(filename: str, class_name: str) -> ast.ClassDef:
    path = WORKER_ROOT / filename
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )


def _method_size(cls: ast.ClassDef, method_name: str) -> int:
    method = next(
        node for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == method_name
    )
    return method.end_lineno - method.lineno + 1


def test_duration_repair_coordinator_stays_below_refactoring_ceiling():
    path = WORKER_ROOT / "duration_repair_service.py"
    cls = _class_node("duration_repair_service.py", "DurationRepairService")

    assert cls.end_lineno - cls.lineno + 1 <= 340
    assert _method_size(cls, "repair") <= 140
    assert len(path.read_text(encoding="utf-8").splitlines()) <= 390


def test_duration_repair_stage_classes_remain_focused():
    remux = _class_node("duration_remux_service.py", "DurationRemuxService")
    timestamp = _class_node("duration_timestamp_service.py", "TimestampRepairService")

    assert remux.end_lineno - remux.lineno + 1 <= 120
    assert timestamp.end_lineno - timestamp.lineno + 1 <= 300
    assert max(
        node.end_lineno - node.lineno + 1
        for node in remux.body
        if isinstance(node, ast.FunctionDef)
    ) <= 80
    assert max(
        node.end_lineno - node.lineno + 1
        for node in timestamp.body
        if isinstance(node, ast.FunctionDef)
    ) <= 125


def test_duration_repair_coordinator_does_not_reimplement_stage_tool_logic():
    source = (WORKER_ROOT / "duration_repair_service.py").read_text(encoding="utf-8")

    assert "log_tool_failure(" not in source
    assert "os.replace(" not in source
    assert '"-bsf:v:0"' not in source
    assert '"-new", str(' not in source
    assert '"mkvmerge", "-o"' not in source


def test_duration_repair_services_stay_qt_independent():
    for filename in (
        "duration_repair_service.py",
        "duration_repair_runtime.py",
        "duration_repair_commands.py",
        "duration_repair_validation.py",
        "duration_remux_service.py",
        "duration_timestamp_service.py",
        "duration_timing_analyzer.py",
    ):
        source = (WORKER_ROOT / filename).read_text(encoding="utf-8")
        assert "PyQt" not in source
        assert "QtCore" not in source
        assert "QtWidgets" not in source


def test_duration_repair_file_replace_is_owned_by_runtime_boundary():
    direct_replace_files = []
    for filename in (
        "duration_repair_service.py",
        "duration_repair_runtime.py",
        "duration_remux_service.py",
        "duration_timestamp_service.py",
    ):
        path = WORKER_ROOT / filename
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
            and node.attr == "replace"
            for node in ast.walk(tree)
        ):
            direct_replace_files.append(filename)

    assert direct_replace_files == ["duration_repair_runtime.py"]
