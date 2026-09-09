from __future__ import annotations

import ast
import zipfile

import pytest
from pathlib import Path

from dragontools.core.release_packaging import create_source_release_zip
from dragontools.core.release_validation import validate_release


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = PACKAGE_ROOT.parent


@pytest.mark.skipif(
    not (PROJECT_ROOT / "release_manifest.json").is_file(),
    reason="Source-only Projektstand ohne Release-Artefakte.",
)
def test_source_release_roundtrip_validates_cleanly(tmp_path):
    target = tmp_path / "dragontools-source.zip"
    create_source_release_zip(PROJECT_ROOT, target)

    extract_root = tmp_path / "extracted"
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        archive.extractall(extract_root)
        names = archive.namelist()

    assert "release_manifest.json" in names
    assert "requirements-runtime.txt" in names
    assert "requirements-optional.txt" in names
    assert "requirements-test.txt" in names
    assert "requirements-build.txt" in names
    assert "pytest.ini" in names
    assert ".github/workflows/tests.yml" in names
    assert "INTEGRATION_TESTS.md" in names
    assert "dragontools/tests/test_real_dv_hdr_integration.py" in names
    assert not any("__pycache__" in name for name in names)
    assert not any(".pytest_cache" in name for name in names)
    assert not any(".mypy_cache" in name for name in names)
    assert not any(".ruff_cache" in name for name in names)
    assert not any(name.endswith((".pyc", ".pyo")) for name in names)
    excluded_roots = {".venv", "venv", "build", "dist", "third_party", "projekt", "git release"}
    assert not any(name.split("/", 1)[0].casefold() in excluded_roots for name in names)
    assert not any(name.split("/", 1)[0].casefold().startswith(".pytest_tmp") for name in names)

    checks = validate_release(extract_root, mode="source")
    errors = [check for check in checks if check.status == "error"]
    assert errors == []
    by_title = {check.title: check for check in checks}
    assert by_title["Runtime-Abhängigkeiten"].status == "ok"
    assert by_title["Optionale Abhängigkeiten"].status == "ok"
    assert by_title["Testumgebung"].status == "ok"
    assert by_title["Build-Umgebung"].status == "ok"
    assert by_title["CI-Workflow"].status == "ok"
    assert by_title["DV/HDR-Integrationstests"].status == "ok"


def test_architecture_tests_do_not_depend_on_project_cwd():
    offenders: list[str] = []
    tests_root = PACKAGE_ROOT / "tests"
    for path in sorted(tests_root.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id != "Path" or not node.args:
                continue
            first = node.args[0]
            if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
                continue
            value = first.value.replace("\\", "/")
            if value == "dragontools" or value.startswith("dragontools/"):
                offenders.append(f"{path.name}:{node.lineno}:{first.value}")

    assert offenders == []
