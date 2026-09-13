from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
WORKER = PACKAGE_ROOT / "worker"


def _loc(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def test_source_visual_checker_remains_orchestration_sized():
    assert _loc(WORKER / "source_visual_check.py") <= 250
    assert _loc(WORKER / "source_visual_sampling.py") <= 190


def test_postprocess_and_trickplay_do_not_call_log_objects_directly():
    for name in ("trickplay_service.py", "postprocess_runner.py", "postprocess_async.py"):
        source = (WORKER / name).read_text(encoding="utf-8")
        assert "getattr(self.log" not in source
        assert "dispatch_log(" in source


def test_log_dispatch_contains_qt_emit_boundary():
    source = (WORKER / "log_dispatch.py").read_text(encoding="utf-8")
    assert 'getattr(log, "emit", None)' in source
