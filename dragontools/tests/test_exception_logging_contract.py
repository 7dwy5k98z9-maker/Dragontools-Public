from __future__ import annotations

import ast
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_product_code_has_no_silent_broad_exception_pass_blocks():
    offenders: list[str] = []
    for path in PACKAGE_ROOT.rglob("*.py"):
        if "tests" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            broad = node.type is None or isinstance(node.type, ast.Name) and node.type.id == "Exception"
            if broad and len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                offenders.append(f"{path.relative_to(PACKAGE_ROOT)}:{node.lineno}")
    assert offenders == []
