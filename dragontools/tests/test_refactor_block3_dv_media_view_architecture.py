from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _class(rel: str, name: str) -> ast.ClassDef:
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    return next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)


def test_dv_remux_thread_delegates_file_transaction():
    cls = _class("worker/dv_remux_thread.py", "DVRemuxThread")
    method = next(
        node for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == "_remux_file_safe"
    )
    source = (ROOT / "worker/dv_remux_thread.py").read_text(encoding="utf-8")
    assert "DVRemuxJobRunner" in source


def test_dv_remux_responsibilities_are_split_into_focused_modules():
    expected = {
        "worker/dv_remux_process.py",
        "worker/dv_remux_audio.py",
        "worker/dv_remux_muxers.py",
        "worker/dv_remux_pipeline.py",
        "worker/dv_remux_output.py",
        "worker/dv_remux_job.py",
    }
    assert all((ROOT / rel).is_file() for rel in expected)


def test_new_refactor_modules_are_release_smoke_checked():
    from dragontools.core.release_validation_package import _SMOKE_MODULES

    covered = {path.as_posix() for path in _SMOKE_MODULES}
    expected = {
        "worker/dv_remux_components.py",
        "worker/dv_remux_process.py",
        "worker/dv_remux_audio.py",
        "worker/dv_remux_muxers.py",
        "worker/dv_remux_pipeline.py",
        "worker/dv_remux_output.py",
        "worker/dv_remux_job.py",
        "worker/dv_remux_thread.py",
        "gui/media_library_dialog_contracts.py",
        "gui/media_library_dialog_options.py",
        "gui/media_library_status_tab.py",
        "gui/media_library_mapping_tab.py",
        "gui/media_library_search_tab.py",
        "gui/media_library_sql_tab.py",
    }
    assert expected <= covered
