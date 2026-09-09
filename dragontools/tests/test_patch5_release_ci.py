from __future__ import annotations

import json
from pathlib import Path

import pytest

from dragontools.core.release_validation import (
    _check_build_environment,
    _check_ci_workflow,
    _check_dv_hdr_integration_contract,
    _check_optional_environment,
    _check_runtime_environment,
    _check_test_environment,
)
from dragontools.tests import conftest as project_conftest
from dragontools.tests.ci_requirements import external_media_environment


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = PACKAGE_ROOT.parent


@pytest.mark.skipif(
    not (PROJECT_ROOT / "release_manifest.json").is_file(),
    reason="Source-only Projektstand ohne Release-Artefakte.",
)
def test_patch5_release_contract_files_are_present():
    manifest = json.loads((PROJECT_ROOT / "release_manifest.json").read_text(encoding="utf-8"))

    assert manifest["runtime_environment_included"] is True
    assert manifest["optional_environment_included"] is True
    assert manifest["ci_workflow_included"] is True
    assert manifest["dv_hdr_integration_tests_included"] is True
    assert manifest["build_environment_included"] is True
    assert (PROJECT_ROOT / "requirements-runtime.txt").is_file()
    assert (PROJECT_ROOT / "requirements-optional.txt").is_file()
    assert (PROJECT_ROOT / "requirements-build.txt").is_file()
    assert (PROJECT_ROOT / ".github" / "workflows" / "tests.yml").is_file()
    assert (PROJECT_ROOT / "INTEGRATION_TESTS.md").is_file()


@pytest.mark.skipif(
    not (PROJECT_ROOT / "release_manifest.json").is_file(),
    reason="Source-only Projektstand ohne Release-Artefakte.",
)
def test_patch5_release_checks_accept_current_declared_environment():
    assert _check_runtime_environment(PROJECT_ROOT).status == "ok"
    assert _check_optional_environment(PROJECT_ROOT).status == "ok"
    assert _check_test_environment(PROJECT_ROOT).status == "ok"
    assert _check_build_environment(PROJECT_ROOT).status == "ok"
    assert _check_ci_workflow(PROJECT_ROOT).status == "ok"
    assert _check_dv_hdr_integration_contract(PROJECT_ROOT).status == "ok"


def test_runtime_dependency_check_rejects_missing_cryptography(tmp_path):
    (tmp_path / "requirements-runtime.txt").write_text("PyQt6>=6.4,<7\n", encoding="utf-8")
    result = _check_runtime_environment(tmp_path)

    assert result.status == "error"
    assert "cryptography" in result.detail


def test_test_environment_must_include_runtime_requirements(tmp_path):
    (tmp_path / "requirements-runtime.txt").write_text(
        "PyQt6>=6.4,<7\ncryptography>=42,<51\n", encoding="utf-8"
    )
    (tmp_path / "requirements-test.txt").write_text(
        "pytest>=8\npytest-qt>=4.4\n", encoding="utf-8"
    )
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\nqt_api = pyqt6\nmarkers =\n    dv_hdr_integration: x\n",
        encoding="utf-8",
    )

    result = _check_test_environment(tmp_path)

    assert result.status == "error"
    assert "requirements-runtime.txt" in result.detail


def test_required_qt_mode_fails_instead_of_silently_skipping(monkeypatch):
    monkeypatch.setenv("DRAGONTOOLS_REQUIRE_QT_TESTS", "1")
    monkeypatch.setattr(project_conftest, "missing_qt_dependencies", lambda: ("PyQt6", "pytest-qt"))

    with pytest.raises(pytest.UsageError, match="PyQt6"):
        project_conftest.pytest_sessionstart(None)


def test_required_dv_hdr_mode_fails_when_real_tools_are_missing(monkeypatch):
    monkeypatch.delenv("DRAGONTOOLS_REQUIRE_QT_TESTS", raising=False)
    monkeypatch.setenv("DRAGONTOOLS_REQUIRE_DV_HDR_INTEGRATION", "1")

    class MissingEnvironment:
        missing = ("dovi_tool", "hdr10plus_tool", "MP4Box")

    monkeypatch.setattr(project_conftest, "external_media_environment", lambda: MissingEnvironment())

    with pytest.raises(pytest.UsageError, match="dovi_tool"):
        project_conftest.pytest_sessionstart(None)


def test_external_media_environment_accepts_explicit_tool_paths(tmp_path, monkeypatch):
    paths = {}
    for env_name, filename in (
        ("DRAGONTOOLS_FFMPEG", "ffmpeg"),
        ("DRAGONTOOLS_FFPROBE", "ffprobe"),
        ("DRAGONTOOLS_DOVI_TOOL", "dovi_tool"),
        ("DRAGONTOOLS_HDR10PLUS_TOOL", "hdr10plus_tool"),
        ("DRAGONTOOLS_MP4BOX", "MP4Box"),
    ):
        path = tmp_path / filename
        path.write_bytes(b"tool")
        monkeypatch.setenv(env_name, str(path))
        paths[env_name] = path.resolve()

    env = external_media_environment()

    assert env.missing == ()
    assert Path(env.dovi_tool) == paths["DRAGONTOOLS_DOVI_TOOL"]
    assert Path(env.hdr10plus_tool) == paths["DRAGONTOOLS_HDR10PLUS_TOOL"]
    assert Path(env.mp4box) == paths["DRAGONTOOLS_MP4BOX"]
