"""Protect the seven boundaries identified by the 9.8.5 technical review."""
import importlib.util
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from dragontools.core import bitmap_subtitle_ocr as ocr
from dragontools.core.language_detection import detect_text_language, LanguageDetectionResult
from dragontools.tests.test_patch_i_language_detection import _Settings, _Tools, _stream_issue
from dragontools.worker import media_stream_metadata_guard as guard
from dragontools.worker.media_library_fix_service import MediaLibraryFixService


QT_TEST_RUNTIME_AVAILABLE = (
    importlib.util.find_spec("PyQt6") is not None
    and importlib.util.find_spec("pytestqt") is not None
)


def _draft(tmp_path):
    media = tmp_path / "movie.mkv"
    media.write_bytes(b"original")
    return ocr.write_pending_draft(
        media_path=media, stream_ordinal=1, stream_index=2,
        codec="hdmv_pgs_subtitle", source_language="de", forced=False,
        cues=[ocr.BitmapOcrCue(1, 1, 2, "Hallo", .99)], min_confidence=.75,
    )


def test_untrusted_ocr_path_cannot_delete_unrelated_file(tmp_path):
    draft = _draft(tmp_path)
    victim = tmp_path / "important.txt"
    victim.write_text("preserve")
    report_path = Path(draft.report_path)
    report = ocr.load_ocr_report(report_path)
    report["draft_path"] = str(victim)
    report_path.write_text(json.dumps(report))
    with pytest.raises(ValueError):
        ocr.finalize_ocr_report(report_path, ["Hallo"])
    assert victim.read_text() == "preserve"
    assert not list(tmp_path.glob("*.srt"))


def test_report_changed_during_review_is_rejected(tmp_path):
    draft = _draft(tmp_path)
    displayed = ocr.load_ocr_report(draft.report_path)
    changed = dict(displayed, forced=True)
    Path(draft.report_path).write_text(json.dumps(changed))
    with pytest.raises(ValueError):
        ocr.finalize_ocr_report(draft.report_path, ["Hallo"], expected_report=displayed)


def test_ocr_concurrent_sidecar_is_preserved(tmp_path, monkeypatch):
    draft = _draft(tmp_path)
    choose = ocr._next_sidecar_path
    occupied = []
    def racing_writer(*args, **kwargs):
        path = choose(*args, **kwargs)
        if not occupied:
            path.write_text("existing user subtitle")
            occupied.append(path)
        return path
    monkeypatch.setattr(ocr, "_next_sidecar_path", racing_writer)
    final = ocr.finalize_ocr_report(draft.report_path, ["Hallo"])
    assert occupied[0].read_text() == "existing user subtitle"
    assert final != occupied[0] and "Hallo" in final.read_text()


def test_pending_pair_is_create_only(tmp_path):
    first = _draft(tmp_path)
    before = Path(first.report_path).read_bytes()
    with pytest.raises(FileExistsError):
        _draft(tmp_path)
    assert Path(first.report_path).read_bytes() == before


def test_shared_cyrillic_script_is_not_russian_evidence():
    result = detect_text_language("Це українські субтитри. Їжак іде до лісу. Ми розмовляємо українською мовою.")
    assert not result.accepted


def test_japanese_quote_does_not_override_english():
    result = detect_text_language(("This is an English subtitle and we are talking in English. " * 30) + "こんにちは")
    assert result.language != "ja"


def test_detection_abort_prevents_metadata_write(tmp_path, monkeypatch):
    worker = SimpleNamespace(abort_requested=False)
    service = MediaLibraryFixService(db_path="unused", settings=_Settings(), tools=_Tools(), worker=worker)
    def detect(issue):
        worker.abort_requested = True
        return LanguageDetectionResult("de", .99, True)
    monkeypatch.setattr(service._language_service, "detect", detect)
    monkeypatch.setattr(service._language_service, "apply_detected_language", lambda *a: pytest.fail("write after abort"))
    assert service.execute(_stream_issue(tmp_path)).status == "skipped"


def _probe(monkeypatch, issue, **changes):
    stream = dict(index=issue.stream_index, codec_type="audio", codec_name=issue.codec,
                  tags={"language": issue.language, "title": issue.track_title},
                  channels=issue.channels, disposition={"forced": 0})
    stream.update(changes)
    monkeypatch.setattr(guard, "run_tool", lambda *a, **kw: SimpleNamespace(
        returncode=0, aborted=False, stdout=json.dumps({"streams": [stream]})))


def test_replaced_source_is_not_modified(tmp_path, monkeypatch):
    issue = _stream_issue(tmp_path)
    Path(issue.path).write_bytes(b"replacement media")
    monkeypatch.setattr(guard, "apply_mkv_track_metadata", lambda *a, **kw: pytest.fail("stale write"))
    assert not guard.edit_queued_track(issue, tools=_Tools(), title="Deutsch")[0]
    assert Path(issue.path).read_bytes() == b"replacement media"


@pytest.mark.parametrize("changes", [
    {"index": 99}, {"codec_name": "aac"},
    {"tags": {"language": "en", "title": "Director Commentary"}},
])
def test_live_track_identity_must_match_snapshot(tmp_path, monkeypatch, changes):
    issue = replace(_stream_issue(tmp_path), stream_ordinal=1)
    _probe(monkeypatch, issue, **changes)
    monkeypatch.setattr(guard, "apply_mkv_track_metadata", lambda *a, **kw: pytest.fail("stale write"))
    assert not guard.edit_queued_track(issue, tools=_Tools(), title="Deutsch")[0]


@pytest.mark.parametrize("late_event", ["abort", "replacement", "none"])
def test_metadata_commit_checks_late_events(tmp_path, monkeypatch, late_event):
    issue = replace(_stream_issue(tmp_path), stream_ordinal=1)
    worker = SimpleNamespace(abort_requested=False)
    _probe(monkeypatch, issue)
    def edit(path, **kwargs):
        assert Path(path) != Path(issue.path)
        Path(path).write_bytes(b"edited copy")
        if late_event == "abort":
            worker.abort_requested = True
        if late_event == "replacement":
            Path(issue.path).write_bytes(b"external replacement")
        return True, "edited"
    monkeypatch.setattr(guard, "apply_mkv_track_metadata", edit)
    ok, _ = guard.edit_queued_track(issue, tools=_Tools(), worker=worker, title="Deutsch")
    assert ok == (late_event == "none")
    expected = {"abort": b"media", "replacement": b"external replacement", "none": b"edited copy"}
    assert Path(issue.path).read_bytes() == expected[late_event]
    assert not list(tmp_path.glob(".dragon_track_*"))


def test_manual_queue_entry_is_not_owned_by_watch(monkeypatch):
    pytest.importorskip("PyQt6")
    from dragontools.gui import convert_widget_watch_intake as intake
    scheduled = []
    monkeypatch.setattr(intake, "QTimer", SimpleNamespace(singleShot=lambda delay, fn: scheduled.append(fn)))
    class Converter(intake.ConvertWidgetWatchMixin):
        def __init__(self):
            self.started = False
            item = object()
            self.file_list = SimpleNamespace(item_for_path=lambda p: item, get_paths=lambda: ["manual.mkv"])
            self._state = SimpleNamespace(thread=None)
            self.move_cb = SimpleNamespace(isChecked=lambda: False)
        def _is_queue_blocking_move_active(self): return False
        def _active_worker(self): return None
        def _watch_profile_override(self, key): return {}
        def _refresh_queue_window(self): pass
        def _log(self, *args): pass
        def _start(self): self.started = True
    converter = Converter()
    assert converter.enqueue_watch_folder_files(["manual.mkv"], auto_start=True) == []
    for callback in scheduled:
        callback()
    assert not converter.started


def test_shutdown_refuses_live_jellyfin_thread(monkeypatch):
    pytest.importorskip("PyQt6")
    from dragontools.gui import main_window_shutdown as shutdown
    from dragontools.gui import jellyfin_refresh_dispatch as dispatch
    class Active:
        def isRunning(self): return True
    monkeypatch.setattr(dispatch, "_ACTIVE_WORKERS", {Active()})
    monkeypatch.setattr(dispatch, "_SHUTTING_DOWN", False)
    monkeypatch.setattr(shutdown, "stop_metadata_action_thread", lambda *a, **kw: True)
    monkeypatch.setattr(shutdown, "stop_watch_folder_controller", lambda *a: True)
    monkeypatch.setattr(shutdown.QMessageBox, "warning", lambda *a: None)
    assert not shutdown.prepare_main_window_close(SimpleNamespace(_tab_widgets={}), timeout_ms=0)


@pytest.mark.skipif(not QT_TEST_RUNTIME_AVAILABLE, reason="PyQt6 + pytest-qt required")
def test_connection_test_registered_for_application_shutdown(qapp):
    pytest.importorskip("PyQt6")
    from dragontools.gui import jellyfin_refresh_dispatch as dispatch
    from dragontools.gui.jellyfin_connection_test import JellyfinConnectionTestThread
    worker = JellyfinConnectionTestThread("http://localhost", "unused")
    try:
        assert worker in dispatch._ACTIVE_WORKERS
    finally:
        dispatch._ACTIVE_WORKERS.discard(worker)


def test_watch_ownership_tracks_row_not_just_path(monkeypatch):
    pytest.importorskip("PyQt6")
    from dragontools.gui import convert_widget_watch_intake as intake
    scheduled = []
    monkeypatch.setattr(intake, "QTimer", SimpleNamespace(singleShot=lambda delay, fn: scheduled.append(fn)))
    class Converter(intake.ConvertWidgetWatchMixin):
        def __init__(self):
            self.started = False
            self.rows = {}
            self.file_list = SimpleNamespace(
                item_for_path=self.rows.get, get_paths=lambda: list(self.rows),
                add_path=lambda p: self.rows.setdefault(p, object()) is not None,
            )
            self._state = SimpleNamespace(thread=None, file_overrides={})
            self._file_queue = SimpleNamespace(refresh_labels=lambda p: None,
                sync_total_files=lambda: None, sync_queue_order=lambda: None)
            self.move_cb = SimpleNamespace(isChecked=lambda: False)
        def _is_queue_blocking_move_active(self): return False
        def _active_worker(self): return None
        def _watch_profile_override(self, key): return {}
        def _refresh_queue_window(self): pass
        def _maybe_preflight_new_files(self, paths): pass
        def update_queue_label(self, path): pass
        def _log(self, *args): pass
        def _start(self): self.started = True
    converter = Converter()
    assert converter.enqueue_watch_folder_files(["watch.mkv"]) == ["watch.mkv"]
    scheduled.pop()()
    assert converter.started
    converter.started = False
    converter.enqueue_watch_folder_files(["watch.mkv"])
    # Remove and manually add the same path before the deferred start executes.
    converter.rows["watch.mkv"] = object()
    scheduled.pop()()
    assert not converter.started
    assert converter.enqueue_watch_folder_files(["watch.mkv"]) == []


def test_pending_report_race_keeps_other_report_and_removes_own_draft(tmp_path, monkeypatch):
    media = tmp_path / "movie.mkv"
    media.write_bytes(b"media")
    original_open = Path.open
    raced = tmp_path / "movie.track1.ocr.json.pending"
    def race(path, mode="r", *args, **kwargs):
        if path == raced and mode == "x":
            with original_open(path, "w") as handle:
                handle.write("another producer")
        return original_open(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", race)
    with pytest.raises(FileExistsError):
        _draft(tmp_path)
    assert raced.read_text() == "another producer"
    assert not (tmp_path / "movie.track1.ocr.srt.pending").exists()


def test_audio_abort_discards_already_collected_evidence(tmp_path, monkeypatch):
    from dragontools.worker import media_stream_language_service as module
    from dragontools.core.language_detection import LanguageEvidence
    worker = SimpleNamespace(abort_requested=False)
    service = module.MediaStreamLanguageService(settings=_Settings(), tools=_Tools(), worker=worker)
    monkeypatch.setattr(module.FasterWhisperLanguageDetector, "available", lambda: True)
    monkeypatch.setattr(service, "_extract_audio_sample", lambda *a: True)
    def detect(path):
        worker.abort_requested = True
        return LanguageEvidence("de", .99)
    monkeypatch.setattr(service, "_whisper_detector", lambda: SimpleNamespace(detect_file=detect))
    assert not service.detect(_stream_issue(tmp_path)).accepted


@pytest.mark.skipif(not QT_TEST_RUNTIME_AVAILABLE, reason="PyQt6 + pytest-qt required")
def test_settings_dialog_defers_close_until_connection_worker_stops(qapp, monkeypatch):
    pytest.importorskip("PyQt6")
    from dragontools.gui.settings_dialog import SettingsDialog
    from dragontools.gui import settings_dialog as module
    from PyQt6.QtWidgets import QDialog
    dialog = SettingsDialog.__new__(SettingsDialog)
    QDialog.__init__(dialog)
    active = SimpleNamespace(isRunning=lambda: True, requestInterruption=lambda: None, wait=lambda ms: False)
    dialog._jellyfin_connection_test_thread = active
    monkeypatch.setattr(module.QMessageBox, "warning", lambda *a: None)
    dialog.done(QDialog.DialogCode.Accepted)
    assert dialog.result() != QDialog.DialogCode.Accepted
    active.isRunning = lambda: False
    dialog.done(QDialog.DialogCode.Accepted)
    assert dialog.result() == QDialog.DialogCode.Accepted
