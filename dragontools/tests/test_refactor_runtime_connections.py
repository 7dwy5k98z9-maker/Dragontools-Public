from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_release_smoke_covers_all_new_refactor_modules():
    from dragontools.core.release_validation_package import _SMOKE_MODULES

    covered = {path.as_posix() for path in _SMOKE_MODULES}
    expected = {
        "core/batch_preflight_formatting.py",
        "core/batch_preflight_decisions.py",
        "core/batch_preflight_rows.py",
        "core/batch_preflight_report.py",
        "core/media_library_classification.py",
        "core/media_library_scope.py",
        "core/media_library_query.py",
        "core/media_library_search_service.py",
        "core/logger_paths.py",
        "core/logger_verbose.py",
        "core/logger_messages.py",
        "core/media_analyzer_io.py",
        "core/media_analyzer_streams.py",
        "core/move_journal_contracts.py",
        "core/move_journal_storage.py",
        "core/move_journal_resume.py",
        "core/move_journal_utils.py",
        "core/online_metadata_tvdb_resolver.py",
        "core/online_metadata_tvdb_suggestions.py",
        "core/online_metadata_tvdb_transport.py",
        "gui/quality_tester_run_dialog.py",
        "gui/quality_tester_run_config.py",
        "gui/quality_tester_files.py",
        "gui/quality_tester_execution.py",
        "gui/convert_override_lifecycle.py",
        "gui/convert_override_state.py",
        "gui/convert_override_tracks.py",
        "gui/convert_override_groups.py",
        "gui/rules_audio_tab_sections.py",
        "gui/rules_audio_tab_channels.py",
        "gui/rules_audio_tab_state.py",
        "gui/convert_widget_layout_components.py",
        "gui/convert_widget_layout_options.py",
        "gui/convert_widget_layout_runtime.py",
        "gui/convert_widget_queue_add.py",
        "gui/convert_widget_queue_remove.py",
    }
    assert expected <= covered


def test_move_journal_split_error_and_fallback_paths(tmp_path):
    from dragontools.core.move_journal import MoveJournal
    from dragontools.core.move_journal_utils import _json_safe_dict, _read_json_dict

    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    assert _read_json_dict(broken) == {}
    assert _json_safe_dict({"not_json": object()}) == {}

    source = str(tmp_path / "episode.mkv")
    journal = MoveJournal.start(files=[source], root=tmp_path)
    journal.data.pop("run_id")
    journal.finish_file(source, status="ok")
    journal.finish_run(status="completed", keep_active=False)

    assert not journal.path.exists()
    assert list((tmp_path / "MoveJournal" / "Abgeschlossen").glob("*.json"))


def test_split_gui_runtime_dependencies_are_connected(tmp_path):
    video = tmp_path / "episode.mkv"
    video.write_bytes(b"")
    code = r'''
import sys
from types import SimpleNamespace
from PyQt6.QtCore import QSettings, QUrl
from PyQt6.QtWidgets import QApplication, QFileDialog, QVBoxLayout, QWidget
from dragontools.gui.convert_widget_file_queue import FileListWidget
from dragontools.gui.convert_widget_layout import ConvertWidgetLayoutBuilder
from dragontools.gui.convert_widget_queue_add import ConvertWidgetQueueAddMixin
from dragontools.gui.rules_audio_tab import _AudioTab
from dragontools.gui.subtitle_widget import SubtitleWidget

app = QApplication.instance() or QApplication([])
video = sys.argv[1]
settings_path = sys.argv[2]
file_list = FileListWidget()
assert file_list.add_path(video) is True
assert file_list.add_path(video) is False
add_helper = SimpleNamespace(file_list=FileListWidget(), log=lambda *_args: None)
assert ConvertWidgetQueueAddMixin.collect_video_paths_from_urls(
    add_helper, [QUrl.fromLocalFile(video)]
) == [video]
audio_tab = _AudioTab()
assert audio_tab.s71_downmix_target.count() == 2
host = QWidget()
root = QVBoxLayout(host)
settings = QSettings(settings_path, QSettings.Format.IniFormat)
builder = ConvertWidgetLayoutBuilder(host, "x265", settings, SimpleNamespace())
builder._build_progress_section(root)
builder._build_log_section(root)
assert host.progress_bar is not None
assert host.log_edit.isReadOnly()
subtitles = SubtitleWidget()
QFileDialog.getOpenFileNames = lambda *_args, **_kwargs: ([video], "")
subtitles._add_videos(subtitles.ext_list)
assert subtitles.ext_list.count() == 1
'''
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [sys.executable, "-c", code, str(video), str(tmp_path / "settings.ini")],
        cwd=str(Path(__file__).resolve().parents[2]),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
