from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (PACKAGE_ROOT / relative).read_text(encoding="utf-8")


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
