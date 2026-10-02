from __future__ import annotations

import ast
from pathlib import Path


def _class_node(path: Path, name: str) -> ast.ClassDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)


def test_mp4_remux_thread_stays_a_small_qt_orchestrator():
    project = Path(__file__).resolve().parents[1]
    path = project / "worker" / "mp4_remux_thread.py"
    node = _class_node(path, "MP4RemuxThread")
    remux = next(item for item in node.body if isinstance(item, ast.FunctionDef) and item.name == "_remux_file")
    assert remux.name == "_remux_file"

    text = path.read_text(encoding="utf-8")
    assert "commit_staged_output" not in text
    assert "compute_subtitle_plan" not in text
    assert "compute_audio_track_plan" not in text


def test_mp4_remux_services_remain_qt_independent():
    project = Path(__file__).resolve().parents[1]
    for name in (
        "mp4_remux_plan.py",
        "mp4_remux_sidecars.py",
        "mp4_remux_file_service.py",
    ):
        text = (project / "worker" / name).read_text(encoding="utf-8")
        assert "PyQt6" not in text, name
