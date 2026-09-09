from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "dragontools"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names.add(module)
    return names


def test_removed_legacy_dv_modules_stay_removed():
    for rel in (
        "worker/dv_conversion.py",
        "worker/dv_p5_legacy_remux.py",
        "worker/dv_subtitle_exporter.py",
    ):
        assert not (PACKAGE / rel).exists(), rel


def test_workers_do_not_import_helper_contracts_from_base_worker():
    offenders: list[str] = []
    helper_names = {"_no_window_kwargs", "_norm_path", "RemoveFileStatus"}
    for path in (PACKAGE / "worker").glob("*.py"):
        if path.name == "base_worker.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if (node.module or "").endswith("base_worker") and helper_names.intersection(
                alias.name for alias in node.names
            ):
                offenders.append(path.name)
                break
    assert offenders == []


def test_worker_contracts_remain_qt_independent():
    imports = _imports(PACKAGE / "worker" / "worker_contracts.py")
    assert not any(name.startswith("PyQt6") for name in imports)


def test_shared_cleanup_modules_are_part_of_source_tree():
    required = (
        "core/json_io.py",
        "core/online_metadata_cache.py",
        "gui/file_drop_widgets.py",
        "gui/journal_resume_base.py",
        "gui/video_file_input.py",
        "subtitle/tool_logging.py",
        "worker/worker_contracts.py",
    )
    missing = [rel for rel in required if not (PACKAGE / rel).is_file()]
    assert missing == []


def test_process_runner_has_no_legacy_run_cmd_alias():
    text = (PACKAGE / "core" / "process_runner.py").read_text(encoding="utf-8")
    assert "run_cmd = run_analysis_tool" not in text


def test_media_analyzer_has_no_obsolete_detection_wrappers():
    text = (PACKAGE / "core" / "media_analyzer.py").read_text(encoding="utf-8")
    for name in (
        "_detect_dv_profile_from_mediainfo",
        "_detect_hdr_flags_from_mediainfo",
        "_detect_hdr_format_from_ffprobe",
    ):
        assert f"def {name}(" not in text


def test_journals_share_atomic_json_writer():
    for rel in ("core/job_journal.py", "core/move_journal.py"):
        text = (PACKAGE / rel).read_text(encoding="utf-8")
        assert "from .json_io import atomic_write_json as _atomic_write_json" in text
        assert "def _atomic_write_json(" not in text


def test_metadata_providers_share_cache_implementation():
    for rel in (
        "core/online_metadata_tmdb_transport.py",
        "core/online_metadata_tvdb_transport.py",
    ):
        text = (PACKAGE / rel).read_text(encoding="utf-8")
        assert "from .online_metadata_cache import read_metadata_cache, write_metadata_cache" in text
        assert "def _read_cache(" not in text
        assert "def _write_cache(" not in text


def test_worker_contracts_have_no_private_path_alias():
    text = (PACKAGE / "worker" / "worker_contracts.py").read_text(encoding="utf-8")
    assert "_norm_path =" not in text
    assert '"_norm_path"' not in text


def test_dv_remux_has_no_formatting_compatibility_wrappers():
    text = (PACKAGE / "worker" / "dv_remux_thread.py").read_text(encoding="utf-8")
    assert "def format_file_size(" not in text
    assert "def format_duration(" not in text


def test_media_library_dialog_has_no_legacy_widget_mirror():
    text = (PACKAGE / "gui" / "media_library_dialog.py").read_text(encoding="utf-8")
    assert "_expose_legacy_widget_attributes" not in text
    assert "def _scan_worker(" not in text
    assert "def _last_search_rows(" not in text
