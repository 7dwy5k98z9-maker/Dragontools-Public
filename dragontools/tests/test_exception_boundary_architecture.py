from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _function(path: Path, name: str) -> ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)


def test_replacement_reminder_gui_boundary_logs_broad_exception():
    fn = _function(ROOT / "gui" / "main_window_recovery.py", "_maybe_show_replacement_reminders")
    handlers = [node for node in ast.walk(fn) if isinstance(node, ast.ExceptHandler)]
    assert len(handlers) == 1
    handler = handlers[0]
    assert isinstance(handler.type, ast.Name) and handler.type.id == "Exception"
    assert not any(isinstance(node, ast.Pass) for node in ast.walk(handler))
    calls = [node for node in ast.walk(handler) if isinstance(node, ast.Call)]
    assert any(
        isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "_LOG"
        and call.func.attr in {"warning", "exception", "error"}
        for call in calls
    )


def test_process_runner_has_no_catch_all_exception_boundary():
    fn = _function(ROOT / "core" / "process_runner.py", "run_analysis_tool")
    for handler in (node for node in ast.walk(fn) if isinstance(node, ast.ExceptHandler)):
        assert handler.type is not None
        assert not (isinstance(handler.type, ast.Name) and handler.type.id in {"Exception", "BaseException"})


def _broad_handler(fn: ast.FunctionDef) -> ast.ExceptHandler:
    return next(
        node for node in ast.walk(fn)
        if isinstance(node, ast.ExceptHandler)
        and isinstance(node.type, ast.Name)
        and node.type.id == "Exception"
    )


def _handler_has_logger_call(handler: ast.ExceptHandler) -> bool:
    return any(
        isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "_LOG"
        and call.func.attr in {"warning", "exception", "error"}
        for call in ast.walk(handler)
        if isinstance(call, ast.Call)
    )


def test_quiet_move_and_job_recovery_still_log_failures():
    path = ROOT / "gui" / "main_window_recovery.py"
    for name in ("_show_unfinished_move_journal", "_show_unfinished_job_journal"):
        handler = _broad_handler(_function(path, name))
        assert _handler_has_logger_call(handler), f"{name} darf Fehler im quiet-Modus nicht still schlucken"


def test_base_worker_abort_has_no_broad_silent_terminate_catch():
    fn = _function(ROOT / "worker" / "base_worker.py", "request_abort")
    for handler in (node for node in ast.walk(fn) if isinstance(node, ast.ExceptHandler)):
        assert handler.type is not None
        assert not (isinstance(handler.type, ast.Name) and handler.type.id in {"Exception", "BaseException"})
        assert not any(isinstance(node, ast.Pass) for node in ast.walk(handler))
