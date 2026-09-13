from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _lines(relative: str) -> int:
    return len((ROOT / relative).read_text(encoding="utf-8").splitlines())


def test_block5_facades_are_small_orchestration_layers():
    limits = {
        "gui/preflight_series_widget.py": 80,
        "gui/conversion_result_service.py": 100,
        "worker/merge_thread.py": 180,
    }
    for relative, limit in limits.items():
        count = _lines(relative)
        assert count <= limit, f"{relative} ist wieder zu groß: {count} > {limit}"


def test_block5_split_modules_remain_bounded():
    limits = {
        "gui/preflight_series_view.py": 220,
        "gui/preflight_series_paths.py": 180,
        "gui/preflight_series_metadata.py": 220,
        "gui/conversion_result_file_events.py": 180,
        "gui/conversion_result_finish.py": 160,
        "gui/conversion_run_finalizer.py": 240,
        "worker/merge_common.py": 120,
        "worker/merge_analysis.py": 200,
        "worker/merge_plan.py": 140,
        "worker/merge_executor.py": 220,
    }
    for relative, limit in limits.items():
        count = _lines(relative)
        assert count <= limit, f"{relative} ist wieder zu groß: {count} > {limit}"


def test_block5_facades_compose_split_responsibilities():
    checks = {
        "gui/preflight_series_widget.py": {
            "SeriesWidgetViewMixin",
            "SeriesWidgetPathMixin",
            "SeriesWidgetMetadataMixin",
        },
        "gui/conversion_result_service.py": {
            "ConversionResultFileEventsMixin",
            "ConversionResultFinishMixin",
            "ConversionRunFinalizerMixin",
        },
        "worker/merge_thread.py": {
            "MergeAnalysisMixin",
            "MergePlanMixin",
            "MergeExecutorMixin",
        },
    }
    for relative, expected in checks.items():
        source = (ROOT / relative).read_text(encoding="utf-8")
        tree = ast.parse(source)
        class_names = {
            base.id
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            for base in node.bases
            if isinstance(base, ast.Name)
        }
        assert expected <= class_names, f"{relative}: fehlende Mixins {expected - class_names}"


def test_block5_new_modules_are_release_smoke_checked():
    from dragontools.core.release_validation_package import _SMOKE_MODULES

    checked = {path.as_posix() for path in _SMOKE_MODULES}
    expected = {
        "gui/preflight_series_view.py",
        "gui/preflight_series_paths.py",
        "gui/preflight_series_metadata.py",
        "gui/conversion_result_file_events.py",
        "gui/conversion_result_finish.py",
        "gui/conversion_run_finalizer.py",
        "worker/merge_common.py",
        "worker/merge_analysis.py",
        "worker/merge_plan.py",
        "worker/merge_executor.py",
        "worker/merge_thread.py",
    }
    assert expected <= checked


def test_merge_thread_keeps_legacy_helper_names():
    source = (ROOT / "worker/merge_thread.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    assigned = {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert {
        "_UserAbortError",
        "_container_from_path",
        "_container_from_format_name",
        "_parse_fps",
        "_audio_signature",
        "_subtitle_signature",
    } <= assigned
