from __future__ import annotations

import ast
import json
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = PACKAGE_ROOT.parent


def _literal_app_version_assignments(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values: list[str] = []
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(target, ast.Name) and target.id == "APP_VERSION" for target in targets):
            continue
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            values.append(value.value)
    return values


def test_app_version_has_one_python_literal_source():
    from dragontools.core.version import APP_VERSION

    python_files = [PROJECT_ROOT / "DragonToolsV9.py", *PACKAGE_ROOT.rglob("*.py")]
    assignments = {
        path.relative_to(PROJECT_ROOT).as_posix(): _literal_app_version_assignments(path)
        for path in python_files
        if path.is_file()
    }
    literal_sources = {name: values for name, values in assignments.items() if values}

    assert literal_sources == {"dragontools/core/version.py": [APP_VERSION]}


def test_public_package_version_and_settings_share_central_version():
    import dragontools
    from dragontools.core.settings import APP_VERSION as settings_version
    from dragontools.core.version import APP_BUILD_NAME, APP_VERSION

    assert dragontools.__version__ == APP_VERSION == settings_version
    assert APP_BUILD_NAME == f"DragonToolsV{APP_VERSION}"


def test_release_manifest_matches_central_version_and_cli_builder():
    from dragontools.core.version import APP_VERSION

    manifest = json.loads((PROJECT_ROOT / "release_manifest.json").read_text(encoding="utf-8"))

    assert manifest["app_version"] == APP_VERSION
    assert manifest["build_strategy"] == "pyinstaller-cli"
    assert manifest["build_script"] == "build_v9.bat"
    assert manifest["spec_file"] is None


def test_builder_uses_dynamic_build_name_without_old_version_literals():
    build = (PROJECT_ROOT / "build_v9.bat").read_text(encoding="utf-8", errors="replace")
    compatibility = (PROJECT_ROOT / "build_v9_angepasst.bat").read_text(encoding="utf-8", errors="replace")

    assert "runpy.run_path(r'dragontools\\core\\version.py')['APP_VERSION']" in build
    assert 'for /f "delims="' not in build.lower()
    assert 'set "BUILD_NAME=DragonToolsV%APP_VERSION%"' in build
    assert '--name "%BUILD_NAME%"' in build
    assert 'dist\\%BUILD_NAME%' in build
    assert "DragonToolsV9.5" not in build
    assert "DragonToolsV9.6" not in build
    assert "DragonToolsV9.7" not in build
    assert 'build_v9.bat' in compatibility

