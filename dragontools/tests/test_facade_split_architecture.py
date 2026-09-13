from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"


def _production_imports_of(module_name: str) -> list[tuple[Path, int]]:
    hits: list[tuple[Path, int]] = []
    for path in ROOT.rglob("*.py"):
        if "tests" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module == module_name or node.module.endswith("." + module_name):
                    hits.append((path, node.lineno))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in {f"dragontools.core.{module_name}", f"core.{module_name}"}:
                        hits.append((path, node.lineno))
    return hits


def test_paths_is_compatibility_facade_and_production_uses_owned_modules():
    source = (CORE / "paths.py").read_text(encoding="utf-8")
    assert len(source.splitlines()) < 100
    assert "from .path_syntax import *" in source
    assert "from .path_defaults import *" in source
    assert "from .resource_paths import" in source
    assert "from .tool_paths import" in source
    assert _production_imports_of("paths") == []


def test_settings_is_compatibility_facade_and_production_uses_domain_modules():
    source = (CORE / "settings.py").read_text(encoding="utf-8")
    assert len(source.splitlines()) < 40
    for module in (
        "settings_app",
        "settings_access",
        "settings_storage",
        "settings_conversion",
        "settings_metadata",
        "settings_media_library",
        "settings_postprocess",
    ):
        assert f"from .{module} import *" in source
        assert (CORE / f"{module}.py").is_file()
    assert _production_imports_of("settings") == []


def test_legacy_tab_manager_tool_lookup_exists_after_paths_split():
    from dragontools.core.tool_paths import find_tool_in_settings

    assert callable(find_tool_in_settings)
