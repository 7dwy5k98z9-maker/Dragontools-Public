from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _lines(relative: str) -> int:
    return len((ROOT / relative).read_text(encoding="utf-8").splitlines())


def _class_bases(relative: str, name: str) -> set[str]:
    tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)
    return {base.id for base in cls.bases if isinstance(base, ast.Name)}


def test_block6_facades_are_small_orchestration_layers():
    limits = {
        "gui/iso_widget.py": 90,
        "worker/parallel_converter_thread.py": 230,
    }
    for relative, limit in limits.items():
        count = _lines(relative)
        assert count <= limit, f"{relative} ist wieder zu groß: {count} > {limit}"


def test_block6_split_modules_remain_bounded():
    limits = {
        "gui/iso_widget_view.py": 190,
        "gui/iso_widget_inputs.py": 150,
        "gui/iso_widget_runtime.py": 240,
        "worker/parallel_converter_queue.py": 150,
        "worker/parallel_converter_control.py": 120,
        "worker/parallel_converter_lifecycle.py": 150,
    }
    for relative, limit in limits.items():
        count = _lines(relative)
        assert count <= limit, f"{relative} ist wieder zu groß: {count} > {limit}"


def test_iso_widget_composes_separate_view_input_and_runtime_roles():
    bases = _class_bases("gui/iso_widget.py", "ISOWidget")
    assert {"ISOWidgetInputMixin", "ISOWidgetRuntimeMixin", "ISOWidgetViewMixin", "QWidget"} <= bases


def test_parallel_converter_composes_queue_control_and_lifecycle_roles():
    bases = _class_bases("worker/parallel_converter_thread.py", "ParallelConverterThread")
    assert {
        "ParallelConverterCompatibilityMixin",
        "ParallelConverterQueueMixin",
        "ParallelConverterControlMixin",
        "ParallelConverterLifecycleMixin",
        "QObject",
    } <= bases


def test_parallel_split_helpers_remain_qt_independent():
    for relative in (
        "worker/parallel_converter_queue.py",
        "worker/parallel_converter_control.py",
        "worker/parallel_converter_lifecycle.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "PyQt6" not in source
        assert "PySide" not in source
        assert "subprocess" not in source


def test_block6_new_modules_are_release_smoke_checked():
    from dragontools.core.release_validation_package import _SMOKE_MODULES

    checked = {path.as_posix() for path in _SMOKE_MODULES}
    expected = {
        "gui/iso_widget_view.py",
        "gui/iso_widget_inputs.py",
        "gui/iso_widget_runtime.py",
        "worker/parallel_converter_queue.py",
        "worker/parallel_converter_control.py",
        "worker/parallel_converter_lifecycle.py",
    }
    assert expected <= checked
