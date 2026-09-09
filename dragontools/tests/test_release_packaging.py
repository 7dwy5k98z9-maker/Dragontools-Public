from __future__ import annotations

import zipfile
from pathlib import Path

import pytest


def test_source_release_zip_excludes_bytecode_and_dev_caches(tmp_path):
    from dragontools.core.release_packaging import create_source_release_zip

    root = tmp_path / "project"
    (root / "dragontools" / "core" / "__pycache__").mkdir(parents=True)
    (root / "dragontools" / "core" / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "dragontools" / "core" / "__pycache__" / "module.cpython-312.pyc").write_bytes(b"pyc")
    (root / "dragontools" / "legacy.pyo").write_bytes(b"pyo")
    (root / ".pytest_cache").mkdir()
    (root / ".pytest_cache" / "README.md").write_text("cache", encoding="utf-8")
    (root / "help.html").write_text("<html></html>", encoding="utf-8")

    target = tmp_path / "release.zip"
    result = create_source_release_zip(root, target)

    assert result == target
    with zipfile.ZipFile(target) as archive:
        names = set(archive.namelist())
        assert "dragontools/core/module.py" in names
        assert "help.html" in names
        assert not any("__pycache__" in name for name in names)
        assert not any(name.endswith((".pyc", ".pyo")) for name in names)
        assert not any(name.startswith(".pytest_cache/") for name in names)
        assert archive.testzip() is None


def test_source_release_zip_failure_keeps_existing_target(tmp_path, monkeypatch):
    from dragontools.core import release_packaging

    root = tmp_path / "project"
    root.mkdir()
    (root / "file.txt").write_text("content", encoding="utf-8")
    target = tmp_path / "release.zip"
    target.write_bytes(b"existing-release")

    def fail_replace(_src, _dst):
        raise OSError("simulierter Replace-Fehler")

    monkeypatch.setattr(release_packaging.os, "replace", fail_replace)

    with pytest.raises(OSError, match="Replace-Fehler"):
        release_packaging.create_source_release_zip(root, target)

    assert target.read_bytes() == b"existing-release"
    assert not list(tmp_path.glob(".release.zip.partial.*"))


def test_forbidden_release_path_handles_windows_and_posix_paths():
    from dragontools.core.release_packaging import is_forbidden_release_path

    assert is_forbidden_release_path(r"dragontools\\core\\__pycache__\\x.pyc")
    assert is_forbidden_release_path("dragontools/core/x.pyo")
    assert not is_forbidden_release_path("dragontools/core/x.py")


def test_release_packaging_filters_test_and_lint_caches(tmp_path):
    from zipfile import ZipFile
    from dragontools.core.release_packaging import create_source_release_zip

    root = tmp_path / "project"
    root.mkdir()
    (root / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    for name in (".pytest_cache", ".mypy_cache", ".ruff_cache", "__pycache__"):
        cache = root / name
        cache.mkdir()
        (cache / "artifact.bin").write_bytes(b"cache")

    target = tmp_path / "release.zip"
    create_source_release_zip(root, target)

    with ZipFile(target) as archive:
        names = archive.namelist()
    assert names == ["module.py"]


def test_source_release_zip_excludes_local_and_external_trees(tmp_path):
    from dragontools.core.release_packaging import create_source_release_zip

    root = tmp_path / "project"
    root.mkdir()
    (root / "DragonToolsV9.py").write_text("print('ok')\n", encoding="utf-8")
    for name in (
        ".venv",
        "venv",
        "build",
        "dist",
        "third_party",
        "Projekt",
        "git release",
        ".pytest_tmp_run2",
    ):
        folder = root / name
        folder.mkdir()
        (folder / "private.bin").write_bytes(b"not for source releases")

    target = tmp_path / "release.zip"
    create_source_release_zip(root, target)

    with zipfile.ZipFile(target) as archive:
        names = archive.namelist()

    assert names == ["DragonToolsV9.py"]


def test_clean_forbidden_release_artifacts_removes_bytecode_and_caches(tmp_path):
    from dragontools.core.release_packaging import clean_forbidden_release_artifacts

    root = tmp_path / "project"
    cache = root / "dragontools" / "core" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "module.pyc").write_bytes(b"bytecode")
    (root / ".pytest_cache").mkdir()
    (root / ".pytest_cache" / "README.md").write_text("cache", encoding="utf-8")
    (root / "orphan.pyo").write_bytes(b"optimized")
    (root / "keep.py").write_text("VALUE = 1\n", encoding="utf-8")

    removed = clean_forbidden_release_artifacts(root)

    assert removed
    assert not cache.exists()
    assert not (root / ".pytest_cache").exists()
    assert not (root / "orphan.pyo").exists()
    assert (root / "keep.py").is_file()


def test_release_artifact_checks_ignore_excluded_local_environments(tmp_path):
    from dragontools.core.release_packaging import (
        clean_forbidden_release_artifacts,
        find_forbidden_release_artifacts,
    )

    root = tmp_path / "project"
    source_cache = root / "dragontools" / "__pycache__"
    source_cache.mkdir(parents=True)
    (source_cache / "module.pyc").write_bytes(b"source bytecode")
    venv_cache = root / ".venv" / "Lib" / "site-packages" / "demo" / "__pycache__"
    venv_cache.mkdir(parents=True)
    venv_bytecode = venv_cache / "module.pyc"
    venv_bytecode.write_bytes(b"environment bytecode")

    findings = find_forbidden_release_artifacts(root)

    assert source_cache.relative_to(root) in findings
    assert not any(str(path).startswith(".venv") for path in findings)

    clean_forbidden_release_artifacts(root)

    assert not source_cache.exists()
    assert venv_bytecode.read_bytes() == b"environment bytecode"
