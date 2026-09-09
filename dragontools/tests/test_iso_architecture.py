# -*- coding: utf-8 -*-
from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
WORKER_ROOT = PACKAGE_ROOT / "worker"


def _class(filename: str, name: str) -> ast.ClassDef:
    path = WORKER_ROOT / filename
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)


def _method_size(cls: ast.ClassDef, name: str) -> int:
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == name)
    return method.end_lineno - method.lineno + 1


def test_iso_thread_is_lifecycle_coordinator_not_tool_implementation():
    path = WORKER_ROOT / "iso_thread.py"
    cls = _class("iso_thread.py", "ISOThread")
    source = path.read_text(encoding="utf-8")

    assert len(source.splitlines()) <= 350
    assert cls.end_lineno - cls.lineno + 1 <= 320
    assert _method_size(cls, "_process_input") <= 105
    assert "run_tool(" not in source
    assert "NamedTemporaryFile" not in source
    assert '"-fflags"' not in source
    assert "TINFO:" not in source


def test_iso_core_services_remain_qt_independent():
    for filename in (
        "iso_models.py",
        "iso_disc_inspector.py",
        "iso_makemkv_service.py",
        "iso_ffmpeg_fallback_service.py",
        "iso_selection.py",
    ):
        source = (WORKER_ROOT / filename).read_text(encoding="utf-8")
        assert "PyQt6" not in source
        assert "QThread" not in source
        assert "pyqtSignal" not in source


def test_iso_service_sizes_stay_bounded():
    inspector = _class("iso_disc_inspector.py", "ISODiscInspector")
    makemkv = _class("iso_makemkv_service.py", "ISOMakeMKVService")
    ffmpeg = _class("iso_ffmpeg_fallback_service.py", "ISOFFmpegFallbackService")

    assert inspector.end_lineno - inspector.lineno + 1 <= 180
    assert makemkv.end_lineno - makemkv.lineno + 1 <= 150
    assert ffmpeg.end_lineno - ffmpeg.lineno + 1 <= 140

    for cls, limit in ((inspector, 55), (makemkv, 60), (ffmpeg, 90)):
        assert max(
            node.end_lineno - node.lineno + 1
            for node in cls.body
            if isinstance(node, ast.FunctionDef)
        ) <= limit


def test_iso_disc_inspector_has_no_tool_execution_dependency():
    source = (WORKER_ROOT / "iso_disc_inspector.py").read_text(encoding="utf-8")
    assert "subprocess" not in source
    assert "run_tool" not in source
    assert "get_timeout" not in source
