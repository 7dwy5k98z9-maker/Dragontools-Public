from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "gui"


def _method(path: Path, class_name: str, method_name: str) -> ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    return next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == method_name)


def _source(path: Path, node: ast.AST) -> str:
    text = path.read_text(encoding="utf-8")
    return ast.get_source_segment(text, node) or ""


def test_reload_paths_updates_hidden_loaded_lazy_tabs():
    path = GUI / "main_window_settings_actions.py"
    method = _method(path, "MainWindowSettingsActionsMixin", "_reload_all_paths")
    src = _source(path, method)
    assert 'getattr(self, "_tab_widgets", {}).values()' in src
    assert 'self.tabs.widget(i)' not in src
    assert 'callable(reload_paths)' in src


def test_main_window_startup_callbacks_are_parented_to_window_lifecycle():
    path = GUI / "main_window.py"
    init = _source(path, _method(path, "MainWindow", "__init__"))
    helpers = (GUI / "ui_helpers.py").read_text(encoding="utf-8")
    assert "QTimer.singleShot(" not in init
    assert init.count("schedule_window_callback(self,") >= 4
    assert "def schedule_window_callback(" in helpers
    assert "QTimer(widget)" in helpers
    assert "timer.setSingleShot(True)" in helpers
    assert "timer.timeout.connect(timer.deleteLater)" in helpers


def test_update_retry_reuses_lifecycle_bound_scheduler():
    path = GUI / "main_window_help_actions.py"
    method = _method(path, "MainWindowHelpActionsMixin", "_check_for_updates_on_startup")
    src = _source(path, method)
    assert "from .ui_helpers import schedule_window_callback" in src
    assert "schedule_window_callback(self, 3000, self._check_for_updates_on_startup)" in src


def test_media_info_workers_participate_in_global_shutdown_gate():
    media = (GUI / "media_info_dialog.py").read_text(encoding="utf-8")
    shutdown = (GUI / "main_window_shutdown.py").read_text(encoding="utf-8")
    sources = (GUI / "application_worker_sources.py").read_text(encoding="utf-8")
    restart = (GUI / "windows_restart_guard.py").read_text(encoding="utf-8")
    assert "def active_media_info_workers()" in media
    assert "_ACTIVE_MEDIA_INFO_THREADS[id(self._load_thread)] = self._load_thread" in media
    assert "_ACTIVE_MEDIA_INFO_THREADS.pop(id(worker), None)" in media
    assert "from .media_info_dialog import active_media_info_workers" in sources
    assert "SimpleNamespace(iter_shutdown_workers=provider)" in sources
    assert "application_worker_sources(window)" in shutdown
    assert "application_worker_sources(" in restart


def test_tab_visibility_has_last_tab_guard_for_startup_and_runtime():
    path = GUI / "main_window_tabs.py"
    source = path.read_text(encoding="utf-8")
    assert "def ensure_one_visible_tab(owner, visible:" in source
    assert "any(state.get(key, True) for key in keys)" in source
    assert "owner.set_tab_visible_setting(fallback, True)" in source
    assert "visible = ensure_one_visible_tab(self, get_visible_tabs())" in source
    assert source.count("ensure_one_visible_tab(self, get_visible_tabs())") >= 2


def test_unloaded_removed_tab_widgets_are_released_but_loaded_tabs_stay_cached():
    path = GUI / "main_window_tabs.py"
    close_src = _source(path, _method(path, "MainWindowTabsMixin", "_on_tab_close"))
    apply_src = _source(path, _method(path, "MainWindowTabsMixin", "_apply_tab_visibility"))
    for src in (close_src, apply_src):
        assert "removed_widget" in src
        assert "self._tab_widgets.get(key) is None" in src
        assert "removed_widget.deleteLater()" in src


def test_drop_paths_are_deduplicated_with_windows_aware_compare_key():
    from dragontools.gui.drop_path_extractor import _dedupe_drop_paths

    result = _dedupe_drop_paths([
        r"C:\Media\Film.mkv",
        r"c:\media\FILM.mkv",
        "/Media/Film.mkv",
        "/media/Film.mkv",
    ])
    assert result[0] == r"C:\Media\Film.mkv"
    assert len(result) == 3
    assert "/Media/Film.mkv" in result
    assert "/media/Film.mkv" in result


def test_simple_video_input_uses_shared_path_identity_not_unconditional_lowercase():
    source = (GUI / "video_file_input.py").read_text(encoding="utf-8")
    assert "path_compare_key(" in source
    assert "normalize_user_path(" in source
    assert ".resolve()).lower()" not in source
    assert "_extract_paths_from_mime_data(mime)" in source
    assert "_mime_has_file_payload" in source
    assert "url.toLocalFile()" not in source
