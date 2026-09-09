from __future__ import annotations


def test_output_paths_are_reserved_for_parallel_non_overwrite_jobs(tmp_path):
    from dragontools.worker.output_path_service import (
        OutputPathService,
        release_output_path_reservation,
    )

    first = tmp_path / "same.avi"
    second = tmp_path / "same.mkv"
    first.write_text("a", encoding="utf-8")
    second.write_text("b", encoding="utf-8")

    service = OutputPathService(codec="h265", overwrite_original=False)
    _base_a, out_a = service.resolve_output_path(str(first), "mkv")
    _base_b, out_b = service.resolve_output_path(str(second), "mkv")

    try:
        assert out_a != out_b
        assert out_a.endswith("same_H265.mkv")
        assert out_b.endswith("same_H265_1.mkv")
    finally:
        release_output_path_reservation(out_a)
        release_output_path_reservation(out_b)


def test_output_paths_are_reserved_for_parallel_overwrite_temp_jobs(tmp_path):
    from dragontools.worker.output_path_service import (
        OutputPathService,
        release_output_path_reservation,
    )

    first = tmp_path / "same.avi"
    second = tmp_path / "same.mkv"
    first.write_text("a", encoding="utf-8")
    second.write_text("b", encoding="utf-8")

    service = OutputPathService(codec="h265", overwrite_original=True)
    _base_a, out_a = service.resolve_output_path(str(first), "mkv")
    _base_b, out_b = service.resolve_output_path(str(second), "mkv")

    try:
        assert out_a != out_b
        assert "__temp_overwrite__" in out_a
        assert "__temp_overwrite__" in out_b
        assert out_a.endswith("same.mkv")
        assert out_b.endswith("same_1.mkv")
    finally:
        release_output_path_reservation(out_a)
        release_output_path_reservation(out_b)
