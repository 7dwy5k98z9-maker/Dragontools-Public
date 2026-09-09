from __future__ import annotations


def test_collect_project_statistics_counts_sources_and_tests(tmp_path):
    from dragontools.core.project_info import collect_project_statistics

    (tmp_path / "DragonToolsV9.py").write_text("print('x')\n", encoding="utf-8")
    tests = tmp_path / "dragontools" / "tests"
    tests.mkdir(parents=True)
    (tmp_path / "dragontools" / "core.py").write_text("# c\nVALUE = 1\n", encoding="utf-8")
    (tests / "__init__.py").write_text("", encoding="utf-8")
    (tests / "test_demo.py").write_text(
        "def test_one():\n    assert True\n\ndef helper():\n    pass\n",
        encoding="utf-8",
    )

    stats = collect_project_statistics(tmp_path)

    assert stats.dynamic is True
    assert stats.python_files == 4
    assert stats.test_package_files == 2
    assert stats.test_files == 1
    assert stats.static_tests == 1
    assert stats.total_lines > 0
    assert stats.code_lines > 0


def test_about_html_contains_current_stability_summary(tmp_path):
    from dragontools.core.project_info import build_about_html
    from dragontools.core.version import APP_VERSION

    html = build_about_html(tmp_path / "missing")

    assert f"Dragon Tools V{APP_VERSION}" in html
    assert "DV- und HDR10+-Erhalt" in html
    assert "MP4Box" in html and "mkvmerge" in html
    assert "direkten 5-Schritt-Pfad" in html
    assert "Per-Datei-Overrides" in html
    assert "Projektumfang" in html
