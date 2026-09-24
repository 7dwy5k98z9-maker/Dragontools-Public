from __future__ import annotations

import ast
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
GUI_TABS = PACKAGE_ROOT / "gui" / "main_window_tabs.py"
GUI_HELPERS = PACKAGE_ROOT / "gui" / "tab_lazy_loading.py"


def _method(path: Path, class_name: str, method_name: str) -> ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    return next(
        node for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == method_name
    )


def test_tab_load_error_report_contains_full_diagnostics(tmp_path):
    from dragontools.core.gui_error_report import write_tab_load_error_report

    try:
        raise RuntimeError("kaputter Test-Tab")
    except RuntimeError as exc:
        traceback_text = "Traceback (most recent call last):\n  test-frame\nRuntimeError: kaputter Test-Tab"
        report = write_tab_load_error_report(
            tab_key="quality_tester",
            tab_label="Qualitätstester",
            error=exc,
            traceback_text=traceback_text,
            log_root=tmp_path,
        )

    path = Path(report)
    assert path.exists()
    assert "Logging" in path.parts
    assert "ErrorReports" in path.parts
    assert "GUI" in path.parts
    text = path.read_text(encoding="utf-8")
    assert "Tab-Key: quality_tester" in text
    assert "Tab-Name: Qualitätstester" in text
    assert "Fehlertyp: RuntimeError" in text
    assert "kaputter Test-Tab" in text
    assert "test-frame" in text


def test_factory_no_longer_swallows_constructor_exceptions():
    method = _method(GUI_TABS, "MainWindowTabsMixin", "_create_tab_widget")
    assert not any(isinstance(node, ast.ExceptHandler) for node in ast.walk(method))


def test_lazy_loader_keeps_failed_tab_retryable_and_logs_traceback():
    source = GUI_TABS.read_text(encoding="utf-8")
    method = _method(GUI_TABS, "MainWindowTabsMixin", "_ensure_tab_loaded")
    method_source = ast.get_source_segment(source, method) or ""

    assert "traceback.format_exc()" in method_source
    assert "show_tab_load_error(" in method_source
    assert "replace_tab_content(" in method_source
    assert "self._tab_widgets[key] = widget" in method_source

    helper_source = GUI_HELPERS.read_text(encoding="utf-8")
    assert "logger.exception(" in helper_source
    assert "owner._tab_widgets[key] = None" in helper_source
    assert 'QPushButton("Erneut versuchen")' in helper_source
    assert "retry_callback=retry_callback" in helper_source


def test_retry_resolves_current_index_from_stable_tab_key():
    source = GUI_HELPERS.read_text(encoding="utf-8")
    assert "def find_tab_index(owner, key: str)" in source
    assert "owner.tabs.tabBar().tabData(idx) == key" in source
    tabs_source = GUI_TABS.read_text(encoding="utf-8")
    assert "find_tab_index(self, tab_key)" in tabs_source
    assert "self._ensure_tab_loaded(" in tabs_source


def test_tab_replacement_blocks_activation_signal_and_releases_old_widget():
    source = GUI_HELPERS.read_text(encoding="utf-8")
    assert "owner.tabs.blockSignals(True)" in source
    assert "owner.tabs.blockSignals(previous)" in source
    assert "old_widget.deleteLater()" in source
