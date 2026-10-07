from __future__ import annotations

import ast
import sys
import types
import zipfile
from pathlib import Path


def test_public_python_member_is_sanitized_without_breaking_syntax(tmp_path):
    from dragontools.core.release_packaging import _write_public_member

    private_org = "Mark" + "usTools"
    private_author = "Mark" + "us Developer"
    private_user = "Mark" + "u"
    root = tmp_path / "project"
    source = root / "module.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        f'APP_ORG = "{private_org}"\n'
        f'AUTHOR = "{private_author}"\n'
        f'EXAMPLE = r"C:\\\\Users\\\\<USER>\\\\Documents\\\\DragonTools"\n',
        encoding="utf-8",
    )
    target = tmp_path / "public.zip"
    with zipfile.ZipFile(target, "w") as archive:
        _write_public_member(archive, root, source, sanitize=True)
    with zipfile.ZipFile(target) as archive:
        text = archive.read("module.py").decode("utf-8")

    assert private_org not in text
    assert private_author not in text
    assert "DragonTools Team" in text
    ast.parse(text)

def test_python_privacy_scanner_detects_hardcoded_secret(tmp_path):
    from dragontools.core.release_validation_package import _scan_private_markers

    source = tmp_path / "module.py"
    source.write_text('API_KEY = "release-check-secret-0123456789abcdef"\n', encoding="utf-8")

    findings = _scan_private_markers(tmp_path)

    assert any(item.status == "error" and "Python-Secret" in item.title for item in findings)


def test_python_privacy_scanner_ignores_setting_key_constants_and_placeholders(tmp_path):
    from dragontools.core.release_validation_package import _scan_private_markers

    source = tmp_path / "module.py"
    source.write_text(
        'SET_KEY_METADATA_TMDB_API_KEY = "metadata/tmdb/api_key"\n'
        'DEFAULT_JELLYFIN_API_KEY = ""\n'
        'def demo():\n'
        '    connect(api_key="tmdb-key", password="wrong-password")\n',
        encoding="utf-8",
    )

    findings = _scan_private_markers(tmp_path)

    assert not any("Python-Secret" in item.title for item in findings)


def test_loaded_bytecode_exception_does_not_admit_unrelated_stale_pyc(tmp_path, monkeypatch):
    from dragontools.core.release_validation_source import _loaded_project_bytecode_paths

    cache = tmp_path / "dragontools" / "core" / "__pycache__"
    cache.mkdir(parents=True)
    loaded = cache / "loaded.cpython-312.pyc"
    stale = cache / "totally_unrelated_stale.cpython-312.pyc"
    loaded.write_bytes(b"loaded")
    stale.write_bytes(b"stale")

    module = types.ModuleType("dragontools.core.loaded")
    module.__cached__ = str(loaded)
    monkeypatch.setitem(sys.modules, module.__name__, module)

    allowed = _loaded_project_bytecode_paths(tmp_path)

    assert loaded.relative_to(tmp_path) in allowed
    assert cache.relative_to(tmp_path) in allowed
    assert stale.relative_to(tmp_path) not in allowed
