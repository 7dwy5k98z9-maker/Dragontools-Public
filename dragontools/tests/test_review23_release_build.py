from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_update_stable_release_supersedes_same_core_prerelease():
    from dragontools.core.update_check import is_newer_version

    assert is_newer_version("9.8.7", "9.8.7-rc.2") is True
    assert is_newer_version("9.8.7-rc.2", "9.8.7") is False
    assert is_newer_version("9.8.7-rc.10", "9.8.7-rc.2") is True
    assert is_newer_version("9.8.7+build.2", "9.8.7+build.1") is False


def test_release_response_preserves_prerelease_semantics():
    from dragontools.core.update_check import parse_release_response

    payload = json.dumps({"tag_name": "v9.8.7-rc.3"})
    result = parse_release_response(payload, "9.8.7-rc.2")

    assert result.ok is True
    assert result.release is not None
    assert result.release.version == "9.8.7-rc.3"
    assert result.update_available is True


def test_public_source_zip_rejects_hardcoded_python_secret(tmp_path):
    from dragontools.core.release_packaging import create_source_release_zip

    root = tmp_path / "project"
    root.mkdir()
    secret = "sk_" + "live_0123456789abcdef0123456789abcdef"
    (root / "module.py").write_text(f'API_KEY = "{secret}"\n', encoding="utf-8")
    target = tmp_path / "release.zip"
    target.write_bytes(b"previous-safe-release")

    with pytest.raises(RuntimeError, match="möglicher Secrets"):
        create_source_release_zip(root, target)

    assert target.read_bytes() == b"previous-safe-release"


def test_public_source_zip_rejects_symlink_members(tmp_path):
    from dragontools.core.release_packaging import create_source_release_zip

    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")
    link = root / "linked.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are not available in this environment")

    with pytest.raises(RuntimeError, match="Symlink"):
        create_source_release_zip(root, tmp_path / "release.zip")


def test_frozen_bundle_source_check_detects_python_anywhere_under_data(tmp_path):
    from dragontools.core.release_validation_build import _check_no_python_source_bundle

    data = tmp_path / "Daten"
    leaked = data / "dragontools" / "core" / "leaked.py"
    leaked.parent.mkdir(parents=True)
    leaked.write_text("SECRET = 1\n", encoding="utf-8")

    check = _check_no_python_source_bundle(data)

    assert check.status == "error"
    assert "dragontools" in check.detail
    assert "leaked.py" in check.detail


def test_release_document_version_contract_detects_stale_active_heading(tmp_path):
    from dragontools.core.release_validation_source import _check_release_version_references
    from dragontools.core.version import APP_VERSION

    (tmp_path / "README.md").write_text("# DragonTools V0.0.1\n", encoding="utf-8")
    (tmp_path / "PATCH.md").write_text(f"# Patch bis Version {APP_VERSION}\n", encoding="utf-8")
    (tmp_path / "help.html").write_text(f"<title>Dragon Tools V{APP_VERSION}</title>", encoding="utf-8")
    history = tmp_path / "Aenderungshistorie"
    history.mkdir()
    (history / "CHANGELOG.json").write_text(
        json.dumps({"current": APP_VERSION}), encoding="utf-8"
    )

    check = _check_release_version_references(tmp_path)

    assert check.status == "error"
    assert "README.md" in check.detail


def test_release_manifest_requires_explicit_app_version(tmp_path):
    from dragontools.core.release_validation_package import _load_release_manifest

    (tmp_path / "release_manifest.json").write_text(
        json.dumps({"schema_version": 1, "profile": "source-only"}), encoding="utf-8"
    )

    _manifest, check = _load_release_manifest(tmp_path)

    assert check.status == "error"
    assert "app_version" in check.detail


def test_auto_mode_detects_app_bundle_root(tmp_path, monkeypatch):
    import dragontools.core.release_validation as module
    from dragontools.core.version import APP_VERSION

    app = tmp_path / f"DragonToolsV{APP_VERSION}"
    (app / "Daten").mkdir(parents=True)
    (app / f"DragonToolsV{APP_VERSION}.exe").write_bytes(b"exe")
    seen = []
    monkeypatch.setattr(module, "validate_app_bundle", lambda root: seen.append(Path(root)) or [])

    assert module.validate_release(app, mode="auto") == []
    assert seen == [app.resolve()]


def test_runtime_dependency_check_rejects_unbounded_required_package(tmp_path):
    from dragontools.core.release_validation_environment import _check_runtime_environment

    (tmp_path / "requirements-runtime.txt").write_text(
        "PyQt6\ncryptography>=42,<51\ndefusedxml>=0.7.1,<1\npackaging>=26.2,<27\n", encoding="utf-8"
    )

    check = _check_runtime_environment(tmp_path)

    assert check.status == "error"
    assert "Versionsgrenzen" in check.detail
    assert "pyqt6" in check.detail


def test_docx_privacy_scan_detects_private_content(tmp_path):
    import zipfile
    from dragontools.core.release_validation_privacy import _scan_private_markers

    docx = tmp_path / "manual.docx"
    private_name = "Mark" + "us Developer"
    with zipfile.ZipFile(docx, "w") as archive:
        archive.writestr(
            "word/document.xml",
            f'<w:document xmlns:w="urn:test"><w:t>@author: {private_name}</w:t></w:document>',
        )

    checks = _scan_private_markers(tmp_path)

    assert any(item.status == "error" and "DOCX" in item.title for item in checks)



def test_pdf_privacy_scan_detects_private_metadata(tmp_path):
    from pypdf import PdfWriter
    from dragontools.core.release_validation_privacy import _scan_private_markers

    pdf = tmp_path / "manual.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.add_metadata({"/Author": "Mark" + "us Developer"})
    with pdf.open("wb") as handle:
        writer.write(handle)

    checks = _scan_private_markers(tmp_path)

    assert any(item.status == "error" and "PDF" in item.title for item in checks)

def test_release_document_version_contract_checks_docx_core_version(tmp_path):
    import zipfile
    from dragontools.core.release_validation_source import _check_release_version_references
    from dragontools.core.version import APP_VERSION

    (tmp_path / "README.md").write_text(f"# DragonTools V{APP_VERSION}\n", encoding="utf-8")
    (tmp_path / "PATCH.md").write_text(f"# Patch bis Version {APP_VERSION}\n", encoding="utf-8")
    (tmp_path / "help.html").write_text(f"<title>Dragon Tools V{APP_VERSION}</title>", encoding="utf-8")
    history = tmp_path / "Aenderungshistorie"
    history.mkdir()
    (history / "CHANGELOG.json").write_text(json.dumps({"current": APP_VERSION}), encoding="utf-8")
    with zipfile.ZipFile(tmp_path / "DragonToolsV9_Dokumentation.docx", "w") as archive:
        archive.writestr(
            "docProps/core.xml",
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties">'
            '<cp:version>0.0.1</cp:version></cp:coreProperties>',
        )

    check = _check_release_version_references(tmp_path)

    assert check.status == "error"
    assert "cp:version" in check.detail
