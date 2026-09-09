from __future__ import annotations

import ast
from pathlib import Path


def test_move_core_services_are_qt_independent():
    # Diese Imports muessen in Headless-/CI-Tests ohne PyQt funktionieren.
    from dragontools.core.move_file_service import MoveFileService
    from dragontools.core.move_postprocess import record_media_library_move
    from dragontools.core.move_routing import MoveRouter
    from dragontools.core.move_sidecars import MoveSidecarService

    assert MoveFileService is not None
    assert MoveRouter is not None
    assert MoveSidecarService is not None
    assert callable(record_media_library_move)


def test_move_thread_contains_no_direct_destructive_move_implementation():
    source_path = Path(__file__).parents[1] / "worker" / "move_thread.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    destructive_calls: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if isinstance(node.func.value, ast.Name):
            qualified = f"{node.func.value.id}.{node.func.attr}"
            if qualified in {
                "os.replace",
                "os.link",
                "shutil.move",
                "shutil.copytree",
                "shutil.rmtree",
            }:
                destructive_calls.add(qualified)

    assert destructive_calls == set()
    assert "PathSwapTransaction" not in source


def test_move_thread_is_orchestrator_not_monolithic_transfer_class():
    source_path = Path(__file__).parents[1] / "worker" / "move_thread.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    move_thread = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "MoveThread")
    run_method = next(node for node in move_thread.body if isinstance(node, ast.FunctionDef) and node.name == "run")

    # Vor dem Refactoring: ~1050 Klassenzeilen, _move ~145, run ~200.
    # Die Grenzwerte verhindern, dass Transferlogik schleichend wieder in den QThread wandert.
    assert move_thread.end_lineno - move_thread.lineno + 1 < 430
    assert run_method.end_lineno - run_method.lineno + 1 < 80


def test_file_service_moves_simple_file_without_qt(tmp_path):
    from dragontools.core.move_file_service import MoveFileService

    source = tmp_path / "source" / "episode.mkv"
    target_dir = tmp_path / "target"
    source.parent.mkdir()
    source.write_bytes(b"payload")

    service = MoveFileService(
        conflict_mode="skip",
        log=lambda *_args: None,
        wait=lambda: None,
        abort_immediately=lambda: False,
        journal=None,
    )
    ok, result = service.move(source, target_dir)

    assert ok is True
    assert result["ok"] is True
    assert not source.exists()
    assert (target_dir / "episode.mkv").read_bytes() == b"payload"


def test_move_thread_orchestrates_planned_move_end_to_end(tmp_path):
    import pytest

    pytest.importorskip("PyQt6")
    from dragontools.worker.move_thread import MoveThread

    source = tmp_path / "input" / "Film.mkv"
    films = tmp_path / "Filme"
    target = films / "Film"
    source.parent.mkdir()
    target.mkdir(parents=True)
    source.write_bytes(b"video-data")

    worker = MoveThread(
        [str(source)],
        "",
        "",
        str(films),
        planned_targets={str(source): str(target)},
        conflict_mode="skip",
        log_file_path=str(tmp_path / "move.log"),
        move_journal_root=tmp_path / "journal",
    )
    worker.run()

    assert worker.ok_count == 1
    assert worker.error_count == 0
    assert not source.exists()
    assert (target / "Film.mkv").read_bytes() == b"video-data"
