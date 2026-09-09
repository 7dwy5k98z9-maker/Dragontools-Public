from __future__ import annotations

import ast
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def _lines(relative: str) -> int:
    return len((PACKAGE_ROOT / relative).read_text(encoding="utf-8").splitlines())


def _function_lines(relative: str, function_name: str, *, class_name: str | None = None) -> int:
    tree = ast.parse((PACKAGE_ROOT / relative).read_text(encoding="utf-8"))
    nodes = tree.body
    if class_name is not None:
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
        nodes = cls.body
    fn = next(node for node in nodes if isinstance(node, ast.FunctionDef) and node.name == function_name)
    return fn.end_lineno - fn.lineno + 1


def test_subtitle_sidecar_service_keeps_planning_separate():
    assert _lines("worker/subtitle_sidecar_service.py") < 370
    assert _lines("worker/subtitle_sidecar_plan.py") < 160
    assert _function_lines(
        "worker/subtitle_sidecar_service.py", "export_sidecars_result", class_name="SubtitleSidecarService"
    ) < 100


def test_move_file_service_is_a_small_transaction_facade():
    assert _lines("core/move_file_service.py") < 260
    assert _lines("core/move_conflict_transactions.py") < 180
    assert _lines("core/move_transfer_executor.py") < 270
    assert _function_lines("core/move_file_service.py", "move", class_name="MoveFileService") < 80


def test_media_library_paths_is_only_a_compatibility_facade():
    assert _lines("core/media_library_paths.py") < 80
    assert _lines("core/media_library_path_mappings.py") < 300
    assert _lines("core/media_library_series_paths.py") < 320


def test_converter_progress_facade_delegates_specialized_work():
    assert _lines("worker/converter_progress.py") < 90
    assert _lines("worker/converter_media_probe.py") < 90
    assert _lines("worker/converter_progress_parser.py") < 130
    assert _lines("worker/converter_process_executor.py") < 260
