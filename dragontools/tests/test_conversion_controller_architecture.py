from __future__ import annotations

import ast
from pathlib import Path


GUI_DIR = Path(__file__).resolve().parents[1] / "gui"


def _parse(name: str) -> tuple[Path, ast.Module]:
    path = GUI_DIR / name
    return path, ast.parse(path.read_text(encoding="utf-8"))


def test_conversion_controller_is_only_orchestration_facade():
    path, tree = _parse("conversion_controller.py")

    forbidden_import_fragments = {
        "worker.converter_thread",
        "worker.parallel_converter_thread",
        "worker.dv_remux_thread",
        "core.disk_space",
        "core.parallel_settings",
        "rules.rule_loader",
    }
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert not any(
        fragment in module
        for module in imported
        for fragment in forbidden_import_fragments
    )

    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    assert [node.name for node in classes] == ["ConversionController"]


def test_conversion_services_have_bounded_single_responsibilities():
    modules = (
        "conversion_start_coordinator.py",
        "conversion_worker_factory.py",
        "conversion_worker_lifecycle.py",
        "conversion_progress_presenter.py",
        "conversion_diagnostics.py",
    )
    for filename in modules:
        path = GUI_DIR / filename
        assert path.is_file(), filename


def test_conversion_controller_contains_no_direct_process_or_file_operations():
    _path, tree = _parse("conversion_controller.py")
    forbidden_calls = {
        "subprocess.run",
        "subprocess.Popen",
        "shutil.move",
        "shutil.copy",
        "shutil.copy2",
        "os.replace",
        "os.remove",
        "Path.unlink",
    }
    calls: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            calls.add(f"{func.value.id}.{func.attr}")
        elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Call):
            if isinstance(func.value.func, ast.Name):
                calls.add(f"{func.value.func.id}.{func.attr}")
    assert not (calls & forbidden_calls)
