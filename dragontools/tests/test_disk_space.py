from __future__ import annotations

from collections import namedtuple


def test_disk_space_check_reports_warning_when_reserve_is_low(tmp_path, monkeypatch):
    import dragontools.core.disk_space as module

    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(
        module.shutil,
        "disk_usage",
        lambda _path: usage(total=10_000, used=0, free=2_200),
    )
    files = []
    for index, size in enumerate([1_000, 800, 300]):
        path = tmp_path / f"file{index}.mkv"
        path.write_bytes(b"x" * size)
        files.append(str(path))

    result = module.check_conversion_disk_space(
        files,
        parallel_jobs=2,
        overwrite_original=True,
        min_free_after_bytes=500,
        output_overhead_factor=1.0,
    )

    assert result.has_warning
    assert not result.has_critical
    assert result.issues[0].required_bytes == 1_800


def test_disk_space_check_reports_critical_when_temp_outputs_do_not_fit(tmp_path, monkeypatch):
    import dragontools.core.disk_space as module

    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(
        module.shutil,
        "disk_usage",
        lambda _path: usage(total=10_000, used=0, free=1_500),
    )
    first = tmp_path / "a.mkv"
    second = tmp_path / "b.mkv"
    first.write_bytes(b"x" * 1_000)
    second.write_bytes(b"x" * 800)

    result = module.check_conversion_disk_space(
        [str(first), str(second)],
        parallel_jobs=2,
        overwrite_original=False,
        min_free_after_bytes=0,
        output_overhead_factor=1.0,
    )

    assert result.has_critical
    assert "temporären Ausgabedateien" in result.issues[0].message
