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


def test_collect_project_statistics_includes_hdr10plus_generator(tmp_path):
    from dragontools.core.project_info import collect_project_statistics

    (tmp_path / "DragonToolsV9.py").write_text("print('x')\n", encoding="utf-8")
    generator_src = tmp_path / "dragon_hdr10plus_generator" / "src" / "dragon_hdr10plus_generator"
    generator_tests = tmp_path / "dragon_hdr10plus_generator" / "tests"
    generator_src.mkdir(parents=True)
    generator_tests.mkdir(parents=True)
    (generator_src / "cli.py").write_text("VALUE = 1\n", encoding="utf-8")
    (generator_tests / "test_cli.py").write_text(
        "def test_generator():\n    assert True\n",
        encoding="utf-8",
    )

    stats = collect_project_statistics(tmp_path)

    assert stats.dynamic is True
    assert stats.python_files == 3
    assert stats.test_package_files == 1
    assert stats.test_files == 1
    assert stats.static_tests == 1


def test_about_html_is_short_general_overview(tmp_path):
    from dragontools.core.project_info import build_about_html
    from dragontools.core.version import APP_VERSION

    html = build_about_html(tmp_path / "missing")

    assert f"Dragon Tools V{APP_VERSION}" in html
    assert "Video &amp; HDR" in html
    assert "Dolby Vision" in html and "HDR10+" in html
    assert "Projektumfang" in html
    assert "Dragon HDR10+ Generator" in html
    assert "Externe Werkzeuge &amp; optionale Komponenten" in html
    assert "MP4Box" in html and "mkvmerge" in html
    assert "faster-whisper/CTranslate2" in html
    assert "Neuerungen" not in html
    assert "Workflow &amp; Sicherheit" not in html
    assert "Metadaten &amp; Mediathek" not in html
    assert "Entwicklungszeit" not in html
    assert "Shortcuts" not in html
