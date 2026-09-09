# -*- coding: utf-8 -*-
"""Tests für den DVRemuxThread abort_type Bug-Fix und WorkerProtocol."""
from unittest.mock import MagicMock, patch


class TestDVRemuxThreadAbortType:
    """Stellt sicher dass abort_type korrekt mit None initialisiert wird."""

    def test_abort_type_initial_ist_none(self):
        # DVRemuxThread importieren ohne Qt-Eventloop zu benötigen:
        # Wir patchen QThread und QSettings weg.
        import sys
        from types import ModuleType

        # Minimale Qt-Stubs
        qt_stubs = {
            "PyQt6": ModuleType("PyQt6"),
            "PyQt6.QtCore": ModuleType("PyQt6.QtCore"),
        }
        mock_qthread = MagicMock()
        mock_qthread.return_value = MagicMock()
        qt_stubs["PyQt6.QtCore"].QThread = mock_qthread
        qt_stubs["PyQt6.QtCore"].pyqtSignal = MagicMock(return_value=MagicMock())
        qt_stubs["PyQt6.QtCore"].QSettings = MagicMock()

        with patch.dict(sys.modules, qt_stubs):
            # abort_type direkt aus dem Quellcode prüfen ohne Instanziierung
            import ast, os
            src_path = os.path.join(
                os.path.dirname(__file__), "..", "worker", "dv_remux_thread.py"
            )
            with open(src_path, encoding="utf-8") as f:
                source = f.read()

        # Im Quelltext nach 'abort_type' suchen und sicherstellen
        # dass der Wert None (nicht "sofort") ist.
        tree = ast.parse(source)
        abort_type_assignments = []
        for node in ast.walk(tree):
            if isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Attribute):
                    if node.target.attr == "abort_type" and node.value:
                        abort_type_assignments.append(ast.unparse(node.value))

        assert abort_type_assignments, "Kein abort_type-Assignment gefunden"
        for val in abort_type_assignments:
            assert val == "None", (
                f"abort_type sollte mit None initialisiert werden, "
                f"gefunden: {val!r}"
            )

    def test_formatierung_nutzt_shared_converter_utils_ohne_legacy_wrapper(self):
        import ast, os
        src_path = os.path.join(
            os.path.dirname(__file__), "..", "worker", "dv_remux_thread.py"
        )
        with open(src_path, encoding="utf-8") as f:
            source = f.read()

        tree = ast.parse(source)
        func_names = {
            node.name for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
        }
        assert "format_file_size" not in func_names
        assert "format_duration" not in func_names
        assert "from .converter_utils import _fd, _fs" in source



class TestWorkerProtocol:
    """Prüft das neue WorkerProtocol in worker/interfaces.py."""

    def test_protocol_ist_importierbar(self):
        from dragontools.worker.interfaces import WorkerProtocol, PausableWorkerProtocol
        assert WorkerProtocol is not None
        assert PausableWorkerProtocol is not None

    def test_mock_worker_erfüllt_protocol(self):
        from dragontools.worker.interfaces import WorkerProtocol

        class FakeWorker:
            abort_requested: bool = False
            abort_type: str | None = None

            def request_abort(self, mode: str = "sofort") -> None:
                self.abort_requested = True
                self.abort_type = mode

            def cancel(self) -> None:
                self.request_abort()

        fw = FakeWorker()
        assert isinstance(fw, WorkerProtocol)

    def test_inkompletter_mock_erfüllt_protocol_nicht(self):
        from dragontools.worker.interfaces import WorkerProtocol

        class IncompleteWorker:
            abort_requested: bool = False
            # abort_type fehlt absichtlich
            def cancel(self) -> None: ...

        iw = IncompleteWorker()
        assert not isinstance(iw, WorkerProtocol)
