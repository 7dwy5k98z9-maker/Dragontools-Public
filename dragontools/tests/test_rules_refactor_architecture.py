from __future__ import annotations

import ast
from pathlib import Path


PACKAGE_ROOT = Path(__file__).parents[1]


def _source(relative_path: str) -> tuple[str, ast.Module]:
    text = (PACKAGE_ROOT / relative_path).read_text(encoding="utf-8")
    return text, ast.parse(text)


def _function_size(tree: ast.Module, name: str) -> int:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node.end_lineno - node.lineno + 1
    raise AssertionError(f"Funktion fehlt: {name}")


def test_pipeline_selector_remains_a_small_orchestrator():
    text, tree = _source("rules/pipeline_selector.py")
    assert len(text.splitlines()) < 220
    assert _function_size(tree, "resolve_pipeline_context") < 90
    assert "pipeline_capabilities" in text
    assert "pipeline_policy" in text


def test_audio_plan_compute_remains_a_small_orchestrator():
    text, tree = _source("rules/audio_plan.py")
    assert len(text.splitlines()) < 340
    assert _function_size(tree, "compute_audio_track_plan") < 60
    assert "audio_plan_policy" in text


def test_refactored_rule_helpers_stay_focused():
    pipeline_caps, _ = _source("rules/pipeline_capabilities.py")
    pipeline_policy, _ = _source("rules/pipeline_policy.py")
    audio_policy, _ = _source("rules/audio_plan_policy.py")
    assert len(pipeline_caps.splitlines()) < 170
    assert len(pipeline_policy.splitlines()) < 140
    assert len(audio_policy.splitlines()) < 190
