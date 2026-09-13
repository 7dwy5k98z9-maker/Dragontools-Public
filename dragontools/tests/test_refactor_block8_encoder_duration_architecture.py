from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _class(rel: str, name: str) -> ast.ClassDef:
    tree = ast.parse(_source(rel))
    return next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)


def _max_method_lines(rel: str, name: str) -> int:
    cls = _class(rel, name)
    return max(
        node.end_lineno - node.lineno + 1
        for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )


def test_encoder_override_facade_stays_small_and_dialog_focused():
    source = _source("gui/convert_widget_encoder_override.py")
    node = _class("gui/convert_widget_encoder_override.py", "EncoderOverrideDialogHelper")

    assert len(source.splitlines()) < 170
    assert node.end_lineno - node.lineno + 1 < 140
    assert _max_method_lines("gui/convert_widget_encoder_override.py", "EncoderOverrideDialogHelper") <= 45
    assert "scoped_encoder_options" not in source
    assert "QDoubleSpinBox" not in source


def test_encoder_override_split_has_clear_responsibilities():
    controls = _source("gui/convert_widget_encoder_controls.py")
    panels = _source("gui/convert_widget_encoder_panels.py")
    state = _source("gui/convert_widget_encoder_state.py")
    apply = _source("gui/convert_widget_encoder_apply.py")

    assert len(controls.splitlines()) < 150
    assert len(panels.splitlines()) < 170
    assert len(state.splitlines()) < 110
    assert len(apply.splitlines()) < 60
    assert "QDialog" not in controls
    assert "PyQt6" not in state
    assert "PyQt6" not in apply
    assert "update_override" in apply


def test_duration_repair_facade_no_longer_owns_repair_workflow():
    service = _source("worker/duration_repair_service.py")
    orchestrator = _source("worker/duration_repair_orchestrator.py")

    assert len(service.splitlines()) < 230
    assert _max_method_lines("worker/duration_repair_service.py", "DurationRepairService") <= 60
    assert "tool_available(" not in service
    assert "DurationRepairOrchestrator" in service
    assert len(orchestrator.splitlines()) < 220
    assert _max_method_lines("worker/duration_repair_orchestrator.py", "DurationRepairOrchestrator") <= 65


def test_duration_repair_policy_and_archive_are_qt_independent():
    for rel in (
        "worker/duration_repair_policy.py",
        "worker/duration_repair_archive.py",
        "worker/duration_repair_orchestrator.py",
    ):
        source = _source(rel)
        assert "PyQt" not in source
        assert "QtCore" not in source
        assert "QtWidgets" not in source


def test_release_smoke_tracks_block8_modules():
    source = _source("core/release_validation_smoke_modules.py")
    for name in (
        "convert_widget_encoder_state",
        "convert_widget_encoder_panels",
        "convert_widget_encoder_controls",
        "convert_widget_encoder_apply",
        "duration_repair_policy",
        "duration_repair_archive",
        "duration_repair_orchestrator",
    ):
        assert name in source
