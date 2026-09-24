from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_source_zip_bat_requires_release_contract_and_omits_specs():
    text = (ROOT / "DragonTools_Source_ZIP.bat").read_text(encoding="utf-8")
    for required in (
        "README.md",
        "PATCH.md",
        "help.html",
        "release_manifest.json",
        "pytest.ini",
        "INTEGRATION_TESTS.md",
        "requirements-runtime.txt",
        "requirements-optional.txt",
        "requirements-test.txt",
        "requirements-build.txt",
        "requirements-whisper.txt",
    ):
        assert f'CopyRequiredFile "{required}"' in text
    assert "for %%F in (*.spec)" not in text
    assert "Generated .spec files must not be in source ZIP" in text
