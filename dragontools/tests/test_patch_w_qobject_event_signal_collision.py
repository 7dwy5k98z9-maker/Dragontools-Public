from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER_DIR = ROOT / "worker"


def _signal_assignments(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if not isinstance(value, ast.Call):
            continue
        func = value.func
        is_pyqt_signal = (
            isinstance(func, ast.Name) and func.id == "pyqtSignal"
        ) or (
            isinstance(func, ast.Attribute) and func.attr == "pyqtSignal"
        )
        if not is_pyqt_signal:
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


def test_qobject_workers_must_not_shadow_native_event_method_with_signal() -> None:
    """QObject.event() is a native virtual method and must remain callable.

    Declaring ``event = pyqtSignal(...)`` on a QObject/QThread subclass shadows
    that native method. Qt then attempts to dispatch an event through a signal
    object and PyQt raises ``TypeError: native Qt signal is not callable``.
    """
    worker_files = (
        WORKER_DIR / "converter_thread.py",
        WORKER_DIR / "dv_remux_thread.py",
        WORKER_DIR / "parallel_converter_thread.py",
    )

    for path in worker_files:
        signals = _signal_assignments(path)
        assert "event" not in signals, f"{path.name} shadows QObject.event()"
        assert "worker_event" in signals, f"{path.name} must expose worker_event"


def test_worker_event_references_use_non_conflicting_name() -> None:
    offenders: list[str] = []
    for path in WORKER_DIR.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if ".event.emit(" in text or ".event.connect(" in text:
            offenders.append(path.name)
    assert offenders == []
