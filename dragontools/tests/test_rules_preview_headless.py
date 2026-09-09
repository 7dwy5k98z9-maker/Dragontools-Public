from __future__ import annotations


def test_rules_preview_module_has_no_pyqt_runtime_import():
    import ast
    from pathlib import Path

    path = Path(__file__).parents[1] / "core" / "rules_preview.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    assert not any(name.startswith("PyQt6") for name in imports)
