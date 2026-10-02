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
    assert is_forbidden_release_path("dragon_hdr10plus_generator/HDRPlusGenerator.spec")
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
        "ComfyUI_windows_portable",
        "HDRTVDM",
        "Projekt",
        "git release",
        ".pytest_tmp_run2",
    ):
        folder = root / name
        folder.mkdir()
        (folder / "private.bin").write_bytes(b"not for source releases")
    generator = root / "dragon_hdr10plus_generator" / "src" / "dragon_hdr10plus_generator"
    generator.mkdir(parents=True)
    (generator / "cli.py").write_text("VALUE = 1\n", encoding="utf-8")

    target = tmp_path / "release.zip"
    create_source_release_zip(root, target)

    with zipfile.ZipFile(target) as archive:
        names = archive.namelist()

    assert "DragonToolsV9.py" in names
    assert "dragon_hdr10plus_generator/src/dragon_hdr10plus_generator/cli.py" in names
    assert not any(name.startswith(("third_party/", "dist/", "build/", "HDRTVDM/")) for name in names)


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


def test_release_artifact_scan_flags_generated_spec_in_source_tree(tmp_path):
    from dragontools.core.release_packaging import find_forbidden_release_artifacts

    spec = tmp_path / "dragon_hdr10plus_generator" / "HDRPlusGenerator.spec"
    spec.parent.mkdir(parents=True)
    spec.write_text("# generated", encoding="utf-8")

    assert spec.relative_to(tmp_path) in find_forbidden_release_artifacts(tmp_path)


def test_real_project_public_inventory_excludes_private_snapshot_and_review_artifacts():
    from dragontools.core.release_packaging import iter_public_source_files

    root = Path(__file__).resolve().parents[2]
    names = {path.relative_to(root).as_posix() for path in iter_public_source_files(root)}
    assert "dragon_hdr10plus_generator/src/dragon_hdr10plus_generator/cli.py" in names
    assert "dragontools/core/release_packaging.py" in names
    assert "SNAPSHOT_CONTENTS.json" not in names
    assert "SNAPSHOT_README.md" not in names
    assert "PATCH_ABSCHLUSS_9.8.5.md" not in names
    assert not any(name.endswith(".diff") for name in names)
    assert not any(name.startswith("reviews/") for name in names)


def test_public_source_zip_omits_private_snapshot_artifacts(tmp_path):
    from dragontools.core.release_packaging import create_source_release_zip

    root = Path(__file__).resolve().parents[2]
    target = tmp_path / "public-source.zip"
    create_source_release_zip(root, target)
    with zipfile.ZipFile(target) as archive:
        names = set(archive.namelist())
    assert "SNAPSHOT_CONTENTS.json" not in names
    assert "PATCH_ABSCHLUSS_9.8.5.md" not in names
    assert "dragon_hdr10plus_generator/build.bat" in names


def test_privacy_scan_uses_same_public_inventory_as_source_packager():
    from dragontools.core.release_validation_package import _iter_release_text_files

    root = Path(__file__).resolve().parents[2]
    names = {path.relative_to(root).as_posix() for path in _iter_release_text_files(root)}
    assert "PATCH.md" in names
    assert "help.html" in names
    assert "dragon_hdr10plus_generator/build.bat" in names
    assert "PATCH_ABSCHLUSS_9.8.5.md" not in names
    assert "SNAPSHOT_README.md" not in names



def test_public_sanitizer_normalizes_both_private_unc_spellings():
    from dragontools.core.release_packaging import sanitize_public_text

    server = "medien" + "speicher"; payload = rf"forward=//{server}/video/Serien\nbackslash=\\{server}\video\Serien"
    sanitized = sanitize_public_text(payload)

    assert server not in sanitized.casefold()
    assert r"\\<SERVER>" in sanitized
    assert "//<SERVER>" in sanitized
