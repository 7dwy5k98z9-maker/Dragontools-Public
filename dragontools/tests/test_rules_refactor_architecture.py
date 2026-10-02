from __future__ import annotations

import ast
from pathlib import Path


PACKAGE_ROOT = Path(__file__).parents[1]


def _source(relative_path: str) -> tuple[str, ast.Module]:
    text = (PACKAGE_ROOT / relative_path).read_text(encoding="utf-8")
    return text, ast.parse(text)


def test_pipeline_selector_remains_a_small_orchestrator():
    text, tree = _source("rules/pipeline_selector.py")
    assert "pipeline_capabilities" in text
    assert "pipeline_policy" in text


def test_audio_plan_compute_remains_a_small_orchestrator():
    text, tree = _source("rules/audio_plan.py")
    assert "audio_plan_policy" in text
