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
    assert '"watch_folders"' in settings_dialog
    assert "start_watch_folder_controller(self)" in main_window
    assert "ConvertWidgetWatchMixin" in converter
    assert "enqueue_watch_folder_files" in watch_intake


def test_live_workers_support_atomic_watch_override_add() -> None:
    root = Path(__file__).resolve().parents[1]
    single = (root / "worker/converter_thread.py").read_text(encoding="utf-8")
    parallel = (root / "worker/parallel_converter_queue.py").read_text(encoding="utf-8")
    assert "def add_file_with_override" in single
    assert "def add_file_with_override" in parallel
