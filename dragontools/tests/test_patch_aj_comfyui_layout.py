from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / "gui" / "settings_sections" / "video.py"
COMFY = ROOT / "gui" / "settings_sections" / "comfyui_fields.py"


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_comfyui_field_builder_returns_next_free_grid_row():
    tree = _parse(COMFY)
    func = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "build_comfyui_fields")
    returns = [node for node in ast.walk(func) if isinstance(node, ast.Return)]
    assert len(returns) == 1
    assert isinstance(returns[0].value, ast.Constant)
    assert returns[0].value.value == 10


def test_ffmpeg_contrast_row_uses_comfyui_next_free_row():
    tree = _parse(VIDEO)
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "VideoAnalysisSection")
    build = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "build")

    assignment = next(
        node for node in ast.walk(build)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "next_sdr_hdr_row" for target in node.targets)
    )
    assert isinstance(assignment.value, ast.Call)
    assert isinstance(assignment.value.func, ast.Attribute)
    assert assignment.value.func.attr == "_build_comfyui_fields"

    source = VIDEO.read_text(encoding="utf-8")
    assert 'QLabel("Kontrast-Recovery (FFmpeg):"), next_sdr_hdr_row, 0' in source
    assert 'd.sdr_hdr_contrast_spin, next_sdr_hdr_row, 1' in source
    assert '), next_sdr_hdr_row, 2)' in source
    assert 'QLabel("Kontrast-Recovery (FFmpeg):"), 4, 0' not in source
