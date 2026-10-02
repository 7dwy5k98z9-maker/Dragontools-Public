from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_source_zip_bat_delegates_to_canonical_python_packager():
    text = (ROOT / "DragonTools_Source_ZIP.bat").read_text(encoding="utf-8")
    assert "create_source_release_zip" in text
    assert "validate_release" in text
    assert "validate_release('.', mode='source')" not in text
    assert "robocopy" not in text.casefold()
    assert "CreateEntry($entryName" not in text
    assert "DRAGONTOOLS_SOURCE_ZIP_NO_PAUSE" in text


def test_generator_build_keeps_pyinstaller_spec_inside_build_tree_and_fails_bad_smoke():
    text = (ROOT / "dragon_hdr10plus_generator" / "build.bat").read_text(encoding="utf-8")
    assert r'--specpath "%CD%\build"' in text
    assert r'--specpath "%CD%"' not in text
    assert "subprocess.run([exe,'--version']" in text
    assert "json.loads(p.stdout)" in text
    assert "if errorlevel 1" in text
    assert "DRAGON_HDRPLUS_BUILD_NO_PAUSE" in text
    assert "numpy>=2,<3" in text


def test_main_build_runs_smoke_against_final_release_exe():
    text = (ROOT / "build_v9.bat").read_text(encoding="utf-8")
    assert "--smoke-test" in text
    assert "WaitForExit(90000)" in text
    assert "Start-Process -FilePath '%DIST_ROOT%\\%BUILD_NAME%.exe'" in text
    assert "finalen Frozen-Runtime-Smoke" in text
    assert "if errorlevel 1" in text
