from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def _class_node(path: Path, name: str) -> ast.ClassDef:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)


def test_audio_video_match_thread_is_only_qt_adapter():
    path = PACKAGE_ROOT / "worker" / "audio_video_match_thread.py"
    source = path.read_text(encoding="utf-8")
    cls = _class_node(path, "AudioVideoMatchThread")
    method_names = {node.name for node in cls.body if isinstance(node, ast.FunctionDef)}

    assert len(source.splitlines()) <= 140
    assert method_names <= {"__init__", "request_abort", "cancel", "run", "_log"}
    assert "AudioSyncPlanner" not in source
    assert "build_audio_command" not in source
    assert "validate_output" not in source
    assert "AudioVideoMatchService" in source


def test_dv_pipeline_delegates_runtime_concerns():
    path = PACKAGE_ROOT / "worker" / "dv_processing_pipeline.py"
    source = path.read_text(encoding="utf-8")
    cls = _class_node(path, "DVProcessingPipeline")
    run = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "run")

    assert run.end_lineno - run.lineno + 1 <= 55
    assert "TemporaryDirectory" not in source
    assert "traceback.format_exc" not in source
    assert "DVPipelineRunExecutor" in source
    assert "DVPipelineDiagnostics" in source
    assert "DVPreflightService" in source


def test_safety_critical_files_do_not_silently_catch_broad_exception():
    # Broad exception boundaries are allowed at thread/pipeline entry points,
    # but parsing/identity/cleanup helpers must not silently convert arbitrary
    # programming errors into normal fallback results.
    files = [
        PACKAGE_ROOT / "core" / "media_library_repository_moves.py",
        PACKAGE_ROOT / "core" / "move_conflicts.py",
        PACKAGE_ROOT / "core" / "media_library_search_service.py",
        PACKAGE_ROOT / "worker" / "cleanup_service.py",
        PACKAGE_ROOT / "worker" / "source_visual_sampling.py",
    ]
    offenders: list[str] = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if node.type is None:
                offenders.append(f"{path.name}:{node.lineno}: bare except")
                continue
            if isinstance(node.type, ast.Name) and node.type.id in {"Exception", "BaseException"}:
                offenders.append(f"{path.name}:{node.lineno}: {node.type.id}")
    assert offenders == []


def test_converter_thread_no_longer_inherits_legacy_state_alias_mixin():
    source = (PACKAGE_ROOT / "worker" / "converter_thread.py").read_text(encoding="utf-8")
    assert "ConverterThreadCompatibilityMixin" not in source
    assert "converter_thread_compat" not in source
    assert "NestedStateAlias" not in source
    assert "def is_paused" in source
    assert "def abort_requested" in source
    assert "def abort_type" in source
