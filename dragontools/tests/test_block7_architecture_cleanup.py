from __future__ import annotations

import ast
from pathlib import Path


PACKAGE = Path(__file__).resolve().parents[1]


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def test_non_gui_layers_do_not_import_gui_modules():
    offenders: list[str] = []
    for top in ("core", "worker", "rules", "subtitle"):
        for path in (PACKAGE / top).rglob("*.py"):
            for node in ast.walk(_tree(path)):
                if isinstance(node, ast.Import):
                    if any(alias.name.startswith("dragontools.gui") for alias in node.names):
                        offenders.append(str(path.relative_to(PACKAGE)))
                elif isinstance(node, ast.ImportFrom) and node.module:
                    if "gui" in node.module.split("."):
                        offenders.append(str(path.relative_to(PACKAGE)))
    assert offenders == []


def test_gpu_detection_lives_in_core_only():
    assert (PACKAGE / "core" / "gpu_detection.py").is_file()
    assert not (PACKAGE / "gui" / "gpu_detector.py").exists()
    for rel in ("worker/converter_thread.py", "worker/parallel_converter_thread.py"):
        text = (PACKAGE / rel).read_text(encoding="utf-8")
        assert "..core.gpu_detection" in text
        assert "..gui.gpu_detector" not in text


def test_private_methods_are_not_called_across_object_boundaries():
    offenders: list[str] = []
    for path in PACKAGE.rglob("*.py"):
        if "tests" in path.parts:
            continue
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            method = node.func.attr
            if not method.startswith("_") or method.startswith("__"):
                continue
            owner = node.func.value
            if isinstance(owner, ast.Name) and owner.id in {"self", "cls"}:
                continue
            if isinstance(owner, ast.Call) and isinstance(owner.func, ast.Name) and owner.func.id == "super":
                continue
            # Journal factory/start classmethods create an instance and persist it
            # through the class' own private writer; this is not cross-class coupling.
            if (
                isinstance(owner, ast.Name)
                and owner.id == "journal"
                and path.name in {"job_journal.py", "move_journal.py", "replace_journal.py"}
                and method == "_write"
            ):
                continue
            offenders.append(f"{path.relative_to(PACKAGE)}:{node.lineno}:{ast.unparse(owner)}.{method}")
    assert offenders == []


def test_removed_compatibility_shims_stay_removed():
    checks = {
        "worker/worker_contracts.py": ("_norm_path =", '"_norm_path"'),
        "worker/dv_remux_thread.py": ("def format_file_size(", "def format_duration("),
        "gui/media_library_dialog.py": ("_expose_legacy_widget_attributes", "def _scan_worker(", "def _last_search_rows("),
        "gui/movie_renamer_widget.py": ("def _resolve_new_proposals(", "def _add_row(", "def _row_item("),
        "gui/move_lifecycle_coordinator.py": ("def _start_incremental_move(", "def _finish_incremental_move("),
        "gui/move_request_dialogs.py": ("def _handle_series_folder(", "def _handle_shutdown_countdown("),
        "gui/conversion_controller.py": ("Kompatibilitätsdelegates", "def _create_converter_thread(", "def _format_eta("),
        "gui/convert_widget_custom_widgets.py": ("def _on_toggle(",),
    }
    for rel, forbidden in checks.items():
        text = (PACKAGE / rel).read_text(encoding="utf-8")
        for marker in forbidden:
            assert marker not in text, f"{marker!r} unexpectedly present in {rel}"


def test_iso_title_selection_is_qt_independent():
    selection = PACKAGE / "worker" / "iso_selection.py"
    assert selection.is_file()
    text = selection.read_text(encoding="utf-8")
    assert "PyQt6" not in text
    assert "def choose_main_title(" in text
    assert "def _choose_main_title(" not in (PACKAGE / "worker" / "iso_thread.py").read_text(encoding="utf-8")


def test_subtitle_sidecar_service_has_only_structured_export_api():
    tree = _tree(PACKAGE / "worker" / "subtitle_sidecar_service.py")
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "SubtitleSidecarService")
    methods = {node.name for node in cls.body if isinstance(node, ast.FunctionDef)}
    assert "export_sidecars_result" in methods
    assert "export_sidecars" not in methods
