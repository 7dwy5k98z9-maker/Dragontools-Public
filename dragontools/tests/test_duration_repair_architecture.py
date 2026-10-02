# -*- coding: utf-8 -*-
from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
WORKER_ROOT = PACKAGE_ROOT / "worker"


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
