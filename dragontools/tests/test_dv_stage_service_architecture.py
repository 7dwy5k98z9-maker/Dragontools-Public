# -*- coding: utf-8 -*-
from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
WORKER_ROOT = PACKAGE_ROOT / "worker"


def _class_node(path: Path, name: str) -> ast.ClassDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)


def test_dv_stage_coordinator_bleibt_klein_und_ohne_toolausfuehrung():
    path = WORKER_ROOT / "dv_pipeline_stages.py"
    node = _class_node(path, "DVPipelineStages")


    forbidden_calls = {"run_p", "adapter"}
    called_attrs = {
        call.func.attr
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
    }
    assert not (called_attrs & forbidden_calls)


def test_dv_stage_services_bleiben_qt_frei():
    for filename in (
        "dv_video_stage_service.py",
        "dv_dynamic_metadata_service.py",
        "dv_final_mux_service.py",
    ):
        tree = ast.parse((WORKER_ROOT / filename).read_text(encoding="utf-8"))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        assert not any(name.startswith(("PyQt", "PySide")) for name in imports)


def test_dv_stage_services_starten_keine_eigenen_subprocesses():
    for filename in (
        "dv_video_stage_service.py",
        "dv_dynamic_metadata_service.py",
        "dv_final_mux_service.py",
    ):
        source = (WORKER_ROOT / filename).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        assert "subprocess" not in imports
        assert "os.system" not in source
