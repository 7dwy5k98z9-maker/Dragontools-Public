from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (PACKAGE_ROOT / relative).read_text(encoding="utf-8")


def _class(relative: str, name: str) -> ast.ClassDef:
    tree = ast.parse(_source(relative))
    return next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)


def _max_method_lines(relative: str, class_name: str) -> int:
    node = _class(relative, class_name)
    return max(
        child.end_lineno - child.lineno + 1
        for child in node.body
        if isinstance(child, ast.FunctionDef)
    )


def test_v4_facades_are_small_coordinators():
    limits = {
        "core/release_validation.py": 80,
        "core/audio_video_time_mapping.py": 120,
        "worker/converter_strip.py": 90,
        "worker/duration_timestamp_candidate_service.py": 170,
        "worker/converter_stream_args.py": 150,
        "worker/dv_final_mux_service.py": 80,
        "worker/quality_compare_thread.py": 150,
        "worker/quality_test_thread.py": 130,
        "worker/iso_thread.py": 260,
        "gui/conversion_progress_presenter.py": 140,
    }
    for relative, limit in limits.items():
        assert len(_source(relative).splitlines()) <= limit, relative


def test_v4_hot_methods_are_bounded():
    assert _max_method_lines("worker/duration_timestamp_candidate_service.py", "TimestampCandidateService") <= 55
    assert _max_method_lines("worker/converter_strip.py", "ConverterStripHelper") <= 40
    assert _max_method_lines("worker/converter_stream_args.py", "ConverterStreamArgsHelper") <= 40
    assert _max_method_lines("worker/dv_final_mux_service.py", "DVFinalMuxService") <= 25
    assert _max_method_lines("worker/quality_compare_thread.py", "QualityCompareThread") <= 35
    assert _max_method_lines("worker/quality_test_thread.py", "QualityTestThread") <= 30
    assert _max_method_lines("gui/conversion_progress_presenter.py", "ConversionProgressPresenter") <= 25


def test_v4_core_and_service_modules_remain_qt_free():
    modules = (
        "core/release_validation_source.py",
        "core/release_validation_build.py",
        "core/release_validation_app.py",
        "core/audio_video_time_mapping_fit.py",
        "core/audio_video_time_mapping_edges.py",
        "worker/duration_timestamp_candidate_archive.py",
        "worker/duration_timestamp_candidate_validation.py",
        "worker/converter_strip_audio.py",
        "worker/converter_strip_subtitles.py",
        "worker/converter_strip_sidecars.py",
        "worker/quality_process_runner.py",
        "worker/quality_metrics_service.py",
        "worker/quality_compare_service.py",
        "worker/quality_test_service.py",
        "worker/dv_track_preparation_service.py",
        "worker/dv_final_output_service.py",
        "worker/dv_final_metadata_verifier.py",
        "worker/iso_input_processor.py",
    )
    for relative in modules:
        source = _source(relative)
        assert "PyQt6" not in source and "PySide" not in source, relative


def test_new_modules_are_part_of_release_smoke_contract():
    from dragontools.core.release_validation_package import _SMOKE_MODULES

    paths = {path.as_posix() for path in _SMOKE_MODULES}
    for expected in (
        "core/release_validation_source.py",
        "core/audio_video_time_mapping_fit.py",
        "worker/quality_metrics_service.py",
        "worker/dv_final_metadata_verifier.py",
        "worker/iso_input_processor.py",
        "gui/conversion_progress_display.py",
    ):
        assert expected in paths
