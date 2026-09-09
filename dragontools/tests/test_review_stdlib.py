import ast
import importlib
import sys
import unittest
from types import ModuleType
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def _parse_module(relative_path: str) -> ast.Module:
    path = ROOT / relative_path
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
    return names


def _class_def(tree: ast.Module, name: str) -> ast.ClassDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"Klasse {name!r} nicht gefunden")


def _function_def(cls: ast.ClassDef, name: str) -> ast.FunctionDef:
    for node in cls.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Methode {name!r} in {cls.name!r} nicht gefunden")


def _qt_core_stub_modules() -> dict[str, ModuleType]:
    qt_pkg = ModuleType("PyQt6")
    qt_core = ModuleType("PyQt6.QtCore")

    class _QThread:
        def __init__(self, parent=None):
            self._parent = parent

    class _Signal:
        def emit(self, *args, **kwargs):
            return None

    def _pyqt_signal(*args, **kwargs):
        return _Signal()

    qt_core.QThread = _QThread
    qt_core.pyqtSignal = _pyqt_signal
    qt_pkg.QtCore = qt_core
    return {
        "PyQt6": qt_pkg,
        "PyQt6.QtCore": qt_core,
    }


def _reload_module(name: str):
    sys.modules.pop(name, None)
    return importlib.import_module(name)


class TestWorkerImports(unittest.TestCase):
    def test_modules_using_get_tool_paths_import_it(self) -> None:
        candidates = [
            "worker/audio_mux_thread.py",
            "worker/iso_thread.py",
            "worker/merge_thread.py",
            "worker/mp4_remux_thread.py",
        ]
        missing: list[str] = []
        for rel in candidates:
            tree = _parse_module(rel)
            source = (ROOT / rel).read_text(encoding="utf-8")
            if "get_tool_paths(" not in source:
                continue
            if "get_tool_paths" not in _imported_names(tree):
                missing.append(rel)
        self.assertEqual(
            [],
            missing,
            f"get_tool_paths() wird verwendet, aber nicht importiert: {missing}",
        )

    def test_workers_are_instantiable_without_tools_argument(self) -> None:
        fake_tools = SimpleNamespace(
            ffmpeg="ffmpeg",
            ffprobe="ffprobe",
            makemkvcon="makemkvcon",
            mkvmerge="mkvmerge",
        )
        fake_logger = SimpleNamespace(log_file=None)

        with patch.dict(sys.modules, _qt_core_stub_modules()):
            audio_mod = _reload_module("dragontools.worker.audio_mux_thread")
            iso_mod = _reload_module("dragontools.worker.iso_thread")
            merge_mod = _reload_module("dragontools.worker.merge_thread")
            mp4_mod = _reload_module("dragontools.worker.mp4_remux_thread")

        with (
            patch.object(audio_mod, "get_tool_paths", return_value=fake_tools),
            patch.object(iso_mod, "get_tool_paths", return_value=fake_tools),
            patch.object(iso_mod, "create_worker_logger", return_value=fake_logger),
            patch.object(merge_mod, "get_tool_paths", return_value=fake_tools),
            patch.object(merge_mod, "create_worker_logger", return_value=fake_logger),
            patch.object(mp4_mod, "get_tool_paths", return_value=fake_tools),
            patch.object(mp4_mod, "create_worker_logger", return_value=fake_logger),
        ):
            audio = audio_mod.AudioMuxThread(files=[])
            iso = iso_mod.ISOThread(inputs=[])
            merge = merge_mod.MergeThread(files=["a.mkv", "b.mkv"], output_path="out.mkv")
            mp4 = mp4_mod.MP4RemuxThread(files=[])

        self.assertIs(audio.tools, fake_tools)
        self.assertIs(iso.tools, fake_tools)
        self.assertIs(merge.tools, fake_tools)
        self.assertIs(mp4.tools, fake_tools)


class TestConvertWidgetPathHooks(unittest.TestCase):
    def test_load_and_save_paths_are_not_empty_stubs(self) -> None:
        tree = _parse_module("gui/convert_widget.py")
        cls = _class_def(tree, "ConvertWidget")

        for method_name in ("reload_paths", "save_paths"):
            func = _function_def(cls, method_name)
            body = func.body
            self.assertFalse(
                len(body) == 1 and isinstance(body[0], ast.Pass),
                f"{method_name} ist noch ein leeres Stub und reagiert nicht auf Settings-Reloads",
            )

    def test_load_paths_refreshes_toolpaths_cache(self) -> None:
        tree = _parse_module("gui/convert_widget.py")
        cls = _class_def(tree, "ConvertWidget")
        func = _function_def(cls, "reload_paths")

        assigns_tools = any(
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
                and target.attr == "tools"
                for target in node.targets
            )
            for node in ast.walk(func)
        )
        delegates_reload = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "reload_tools"
            for node in ast.walk(func)
        )
        self.assertTrue(assigns_tools, "reload_paths soll self.tools bewusst aktualisieren")
        self.assertTrue(delegates_reload, "reload_paths soll den zentralen Pfadservice nutzen")

        path_tree = _parse_module("gui/convert_widget_paths.py")
        path_cls = _class_def(path_tree, "ConvertWidgetTargetPathService")
        reload_func = _function_def(path_cls, "reload_tools")
        call_names = {
            node.func.id
            for node in ast.walk(reload_func)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertIn("invalidate_tool_paths", call_names)
        self.assertIn("get_tool_paths", call_names)

    def test_save_paths_delegates_to_load_paths(self) -> None:
        tree = _parse_module("gui/convert_widget.py")
        cls = _class_def(tree, "ConvertWidget")
        func = _function_def(cls, "save_paths")

        delegated = False
        for node in ast.walk(func):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                callee = node.func
                if (
                    isinstance(callee.value, ast.Name)
                    and callee.value.id == "self"
                    and callee.attr == "reload_paths"
                ):
                    delegated = True
                    break

        self.assertTrue(delegated, "save_paths soll bewusst an reload_paths delegieren")


class TestBaseWorkerContract(unittest.TestCase):
    def test_baseworker_declares_abort_type_contract(self) -> None:
        tree = _parse_module("worker/base_worker.py")
        cls = _class_def(tree, "BaseWorker")

        has_abort_type = False
        for node in cls.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.target.id == "abort_type":
                    has_abort_type = True
                    break
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "abort_type":
                        has_abort_type = True
                        break
            if has_abort_type:
                break

        self.assertTrue(
            has_abort_type,
            "BaseWorker dokumentiert abort_type als Pflichtattribut, deklariert es aber nicht",
        )

    def test_baseworker_has_abort_type_after_init(self) -> None:
        with patch.dict(sys.modules, _qt_core_stub_modules()):
            mod = _reload_module("dragontools.worker.base_worker")

        worker = mod.BaseWorker()
        self.assertFalse(worker.abort_requested)
        self.assertIsNone(worker.abort_type)

    def test_request_abort_sets_abort_flags(self) -> None:
        with patch.dict(sys.modules, _qt_core_stub_modules()):
            mod = _reload_module("dragontools.worker.base_worker")

        worker = mod.BaseWorker()
        worker.request_abort("nach_datei")
        self.assertTrue(worker.abort_requested)
        self.assertEqual("nach_datei", worker.abort_type)


if __name__ == "__main__":
    unittest.main()
