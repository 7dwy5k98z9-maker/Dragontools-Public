from __future__ import annotations

import json
from pathlib import Path

from dragontools.core.settings_watch import (
    SET_KEY_WATCH_PROCESSED_STATE,
    load_processed_state,
    load_watch_rules,
    save_processed_state,
    save_watch_rules,
)
from dragontools.core.watch_folder import WatchFolderRule, WatchFolderScanner


class _Settings:
    def __init__(self):
        self.data = {}

    def value(self, key, default=None, type=None):
        value = self.data.get(key, default)
        if type is not None:
            try:
                return type(value)
            except Exception:
                return default
        return value

    def setValue(self, key, value):
        self.data[key] = value


def _rule(path: Path, **overrides) -> WatchFolderRule:
    payload = {
        "rule_id": "rule-1",
        "name": "Inbox",
        "path": str(path),
        "recursive": True,
        "codec": "h265",
        "profile_key": "",
        "auto_start": True,
        "enabled": True,
    }
    payload.update(overrides)
    rule = WatchFolderRule.from_mapping(payload)
    assert rule is not None
    return rule


def test_watch_rule_normalizes_invalid_codec_to_h265(tmp_path: Path) -> None:
    rule = _rule(tmp_path, codec="vp9")
    assert rule.codec == "h265"


def test_scanner_waits_until_file_signature_is_stable(tmp_path: Path) -> None:
    source = tmp_path / "movie.mkv"
    source.write_bytes(b"a")
    scanner = WatchFolderScanner(stable_seconds=10)
    rule = _rule(tmp_path)

    assert scanner.scan([rule], now=0) == []
    assert scanner.scan([rule], now=9) == []
    ready = scanner.scan([rule], now=10)
    assert [entry.path for entry in ready] == [str(source.resolve())]


def test_manual_scan_can_override_stability_wait_without_marking_processed(tmp_path: Path) -> None:
    source = tmp_path / "manual.mkv"
    source.write_bytes(b"ready")
    scanner = WatchFolderScanner(stable_seconds=60)
    rule = _rule(tmp_path)

    ready = scanner.scan([rule], now=0, stable_seconds_override=0)
    assert [entry.path for entry in ready] == [str(source.resolve())]
    # A manual discovery is not an acknowledgement. Until conversion reports
    # success, the same source must remain eligible for retry.
    assert len(scanner.scan([rule], now=61)) == 1


def test_signature_change_restarts_stability_window(tmp_path: Path) -> None:
    source = tmp_path / "episode.mkv"
    source.write_bytes(b"a")
    scanner = WatchFolderScanner(stable_seconds=10)
    rule = _rule(tmp_path)

    scanner.scan([rule], now=0)
    source.write_bytes(b"ab")
    assert scanner.scan([rule], now=9) == []
    assert scanner.scan([rule], now=18) == []
    assert len(scanner.scan([rule], now=19)) == 1


def test_acknowledged_signature_is_not_emitted_again_and_survives_restart(tmp_path: Path) -> None:
    source = tmp_path / "film.mp4"
    source.write_bytes(b"content")
    rule = _rule(tmp_path)
    scanner = WatchFolderScanner(stable_seconds=0)

    candidate = scanner.scan([rule], now=0)[0]
    scanner.acknowledge(candidate)
    assert scanner.scan([rule], now=1) == []

    restarted = WatchFolderScanner(stable_seconds=0, processed_state=scanner.processed_state())
    assert restarted.scan([rule], now=2) == []

    source.write_bytes(b"new-content")
    changed = restarted.scan([rule], now=3)
    assert len(changed) == 1
    assert changed[0].path == str(source.resolve())


def test_non_recursive_rule_ignores_nested_video(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    (tmp_path / "top.mkv").write_bytes(b"x")
    (nested / "deep.mkv").write_bytes(b"x")
    scanner = WatchFolderScanner(stable_seconds=0)
    ready = scanner.scan([_rule(tmp_path, recursive=False)], now=0)
    assert {Path(entry.path).name for entry in ready} == {"top.mkv"}


def test_non_video_and_partial_download_files_are_ignored(tmp_path: Path) -> None:
    (tmp_path / "movie.mkv.part").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    (tmp_path / "ready.mkv").write_bytes(b"x")
    scanner = WatchFolderScanner(stable_seconds=0)
    ready = scanner.scan([_rule(tmp_path)], now=0)
    assert [Path(entry.path).name for entry in ready] == ["ready.mkv"]


def test_watch_rule_settings_roundtrip(tmp_path: Path) -> None:
    settings = _Settings()
    original = [_rule(tmp_path, codec="av1", profile_key="anime_av1", auto_start=False)]
    save_watch_rules(settings, original)
    loaded = load_watch_rules(settings)
    assert loaded == original


def test_processed_state_roundtrip_and_limit() -> None:
    settings = _Settings()
    save_processed_state(settings, {"a": "1", "b": "2", "c": "3"}, limit=2)
    assert load_processed_state(settings) == {"b": "2", "c": "3"}
    raw = json.loads(settings.data[SET_KEY_WATCH_PROCESSED_STATE])
    assert list(raw) == ["b", "c"]


def test_patch_g_is_wired_into_settings_main_window_and_converter() -> None:
    root = Path(__file__).resolve().parents[1]
    settings_dialog = (root / "gui/settings_dialog.py").read_text(encoding="utf-8")
    main_window = (root / "gui/main_window.py").read_text(encoding="utf-8")
    converter = (root / "gui/convert_widget.py").read_text(encoding="utf-8")
    watch_intake = (root / "gui/convert_widget_watch_intake.py").read_text(encoding="utf-8")
    watch_controller = (root / "gui/watch_folder_controller.py").read_text(encoding="utf-8")
    watch_bridge = (root / "gui/watch_folder_main_window_bridge.py").read_text(encoding="utf-8")
    layout = (root / "gui/convert_widget_layout_runtime.py").read_text(encoding="utf-8")
    composition = (root / "gui/convert_widget_composition.py").read_text(encoding="utf-8")
    assert '"watch_folders"' in settings_dialog
    assert "start_watch_folder_controller(self)" in main_window
    assert "ConvertWidgetWatchMixin" in converter
    assert "enqueue_watch_folder_files" in watch_intake
    assert "def scan_now" in watch_controller
    assert "stable_seconds_override=0 if manual else None" in watch_controller
    assert "auto_start = False if manual else candidate.auto_start" in watch_controller
    assert "def scan_watch_folders_now" in watch_bridge
    assert "Watchfolder durchsuchen" in layout
    assert "watch_scan_btn.clicked.connect(owner._scan_watch_folders_now)" in composition


def test_live_workers_support_atomic_watch_override_add() -> None:
    root = Path(__file__).resolve().parents[1]
    single = (root / "worker/converter_thread.py").read_text(encoding="utf-8")
    parallel = (root / "worker/parallel_converter_queue.py").read_text(encoding="utf-8")
    assert "def add_file_with_override" in single
    assert "def add_file_with_override" in parallel


def test_recursive_watchfolder_prunes_dragontools_managed_directories(tmp_path):
    root = tmp_path / "WatchRoot"
    normal = root / "Serien" / "Episode.mkv"
    managed = [
        root / "Archiv" / "bundle" / "failed.mkv",
        root / "Fehler" / "crop" / "failed.mkv",
        root / "__temp_overwrite__" / "working.mkv",
        root / "__temp_dv_remux__" / "working.mkv",
        root / "dragontools_dv_abc123" / "working.mkv",
        root / "Archiv" / ".Film.partial" / "staged.mkv",
    ]
    normal.parent.mkdir(parents=True)
    normal.write_bytes(b"ok")
    for path in managed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"managed")

    scanner = WatchFolderScanner(stable_seconds=0)
    found = scanner.scan([_rule(root)])
    assert [Path(item.path).name for item in found] == ["Episode.mkv"]


def test_managed_name_is_allowed_when_it_is_the_configured_watchroot(tmp_path):
    root = tmp_path / "Archiv"
    root.mkdir()
    direct = root / "direct.mkv"
    direct.write_bytes(b"video")

    scanner = WatchFolderScanner(stable_seconds=0)
    found = scanner.scan([_rule(root)])
    assert any(Path(item.path).name == "direct.mkv" for item in found)
