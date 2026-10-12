"""Fast remux startup and responsive, source-aware queue pipeline badges."""
from functools import partial
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import QCheckBox, QListWidget, QListWidgetItem, QWidget

from dragontools.core.models import MediaInfo, VideoStream
from dragontools.core.transaction_identity import stat_identity
from dragontools.gui.convert_widget_queue_badges import ConvertWidgetQueueBadgesMixin
from dragontools.gui.convert_widget_pipeline_preview import ConvertWidgetPipelinePreview
from dragontools.tests.test_patch17_second_review import _mp4_job


@pytest.mark.parametrize("duration", [10.125, 9872.3, 24 * 3600])
def test_converter_reuses_analyzed_duration_without_second_probe(tmp_path, monkeypatch, duration):
    from dragontools.worker import media_analysis_service as module
    source = tmp_path / "film.mkv"
    source.write_bytes(b"VIDEO")
    media = SimpleNamespace(primary_video=object(), duration_s=duration)
    monkeypatch.setattr(module, "analyze_media", lambda *_: media)
    probe = Mock(side_effect=AssertionError("duplicate duration probe"))
    service = module.MediaAnalysisService(tools=None, probe_duration_ms=probe, log=lambda *_: None)
    assert service.analyze(str(source)) == (media, int(duration * 1000), 5)
    probe.assert_not_called()


@pytest.mark.parametrize("duration", [None, 0, -1, float("nan"), float("inf"), 4_299_697])
def test_converter_probes_duration_when_analysis_has_no_reliable_value(tmp_path, monkeypatch, duration):
    from dragontools.worker import media_analysis_service as module
    source = tmp_path / "film.mkv"
    source.touch()
    monkeypatch.setattr(module, "analyze_media", lambda *_: SimpleNamespace(primary_video=object(), duration_s=duration))
    probe = Mock(return_value=12345)
    service = module.MediaAnalysisService(tools=None, probe_duration_ms=probe, log=lambda *_: None)
    assert service.analyze(str(source))[1] == 12345
    probe.assert_called_once_with(str(source))


def test_mp4_starts_ffmpeg_without_reading_entire_source(tmp_path, monkeypatch):
    from dragontools.worker import mp4_remux_file_service as module
    from dragontools.core.output_replace import commit_staged_output
    monkeypatch.setattr(module, "commit_staged_output", partial(commit_staged_output, journal_root=tmp_path / "journals"))
    started = False
    original_open = Path.open

    def guarded_open(path, mode="r", *args, **kwargs):
        if path == source and "r" in mode:
            assert started, "source content was read before FFmpeg started"
        return original_open(path, mode, *args, **kwargs)

    def run(command, *_):
        nonlocal started
        started = True
        Path(command[-1]).write_bytes(b"REMUXED")
        return 0

    service, source, stage, results, media = _mp4_job(tmp_path, run=run)
    monkeypatch.setattr(Path, "open", guarded_open)
    assert service.remux(str(source), str(source), media, current_index=1, total_files=1,
                         user_abort_error=RuntimeError, expected_source_identity=stat_identity(source))
    assert source.read_bytes() == b"REMUXED"


def test_mp4_rejects_changed_source_before_ffmpeg_without_content_probe(tmp_path, monkeypatch):
    run = Mock()
    service, source, _, results, media = _mp4_job(tmp_path, run=run)
    identity = stat_identity(source)
    source.write_bytes(b"MODIFIED SOURCE")
    monkeypatch.setattr("dragontools.worker.mp4_remux_file_service.path_receipt", Mock(side_effect=AssertionError("premature content read")))
    assert not service.remux(str(source), str(source), media, current_index=1, total_files=1,
                             user_abort_error=RuntimeError, expected_source_identity=identity)
    run.assert_not_called()
    assert source.read_bytes() == b"MODIFIED SOURCE"


def test_mp4_thread_captures_identity_before_analysis_without_hash(tmp_path, monkeypatch):
    from dragontools.worker import mp4_remux_thread as module
    source = tmp_path / "film.mkv"
    source.write_bytes(b"ORIGINAL")
    identity = stat_identity(source)
    arguments = []
    service = SimpleNamespace(remux=lambda *a, **kw: arguments.append(kw) or True)
    monkeypatch.setattr(module, "MP4RemuxFileService", lambda **kw: service)
    monkeypatch.setattr(module, "analyze_owned_media", lambda *a, **kw: object())
    signal = SimpleNamespace(emit=lambda *_: None)
    host = SimpleNamespace(tools=None, _logger=None, _current_idx=1, files=[str(source)],
        export_subtitles=False, ignore_subtitles=True, file_result=signal, file_progress=signal,
        _planner=lambda: None, _output_verifier=lambda: None, _log=lambda *_: None,
        _run_ffmpeg_with_progress=lambda *_: 0, _extract_external_subtitles=lambda *_: None,
        _commit_sidecars=lambda *_: None, _cleanup_generated_sidecars=lambda *_: None)
    monkeypatch.setattr(Path, "open", Mock(side_effect=AssertionError("unexpected source read")))
    assert module.MP4RemuxThread._remux_file(host, str(source), str(tmp_path / "out.mp4"))
    assert arguments[0]["expected_source_identity"] == identity


class _Owner(ConvertWidgetQueueBadgesMixin, QWidget):
    def __init__(self, path):
        super().__init__()
        self.default_codec = "h265"
        self.settings = None
        self.tools = SimpleNamespace(ffmpeg="ffmpeg", ffprobe="ffprobe", hdr10plus_generator="")
        self._state = SimpleNamespace(file_overrides={}, preflight_rows_by_path={})
        self.preserve_dv_cb, self.preserve_hdrplus_cb, self.autocrop_cb = [QCheckBox(self) for _ in range(3)]
        self.preserve_dv_cb.setChecked(True)
        self.preserve_hdrplus_cb.setChecked(True)
        self.file_list = QListWidget(self)
        self._ui = SimpleNamespace(file_list=self.file_list)
        item = QListWidgetItem(self.file_list)
        item.setData(Qt.ItemDataRole.UserRole, path)
        self._pipeline_preview = ConvertWidgetPipelinePreview(self)

    def rule_test_preview_options(self, *, probe_generator):
        assert probe_generator is False
        return {"default_encoder_options": {
            "preserve_dv": self.preserve_dv_cb.isChecked(),
            "preserve_hdrplus": self.preserve_hdrplus_cb.isChecked(),
            **getattr(self, "extra_encoder_options", {}),
        }}

    def get_subtitle_rules(self):
        return {}

    def _refresh_queue_window(self):
        pass


def _media(path, *, dv=False, hdr=False, hdrplus=False):
    return MediaInfo(path, [], [], [VideoStream(0, "hevc", 3840, 2160,
        has_dolby_vision=dv, has_hdr10plus=hdrplus,
        color_transfer="smpte2084" if hdr else "bt709", bit_depth=10 if hdr else 8,
        color_primaries="bt2020" if hdr else "bt709")], duration_s=10, is_hdr=hdr,
        dolby_vision=dv, dv_profile="8" if dv else None, has_hdr10plus=hdrplus)


@pytest.fixture
def queue_owner(tmp_path, qtbot):
    source = tmp_path / "The Dark Knight Rises.mkv"
    source.write_bytes(b"SOURCE")
    owner = _Owner(str(source))
    qtbot.addWidget(owner)
    yield owner, source
    owner._pipeline_preview.shutdown()
    for worker in owner._pipeline_preview.workers_for_shutdown():
        assert worker.wait(5000)
    qtbot.waitUntil(lambda: not owner._pipeline_preview.workers_for_shutdown(), timeout=5000)


@pytest.mark.parametrize("dv,hdr,hdrplus,label", [
    (True, True, False, "DV"), (False, True, False, "HDR"),
    (False, True, True, "HDR10+"), (True, True, True, "DV + HDR10+"),
    (False, False, False, "Standard"),
])
def test_queue_detects_pipeline_without_manual_preflight(queue_owner, qtbot, monkeypatch, dv, hdr, hdrplus, label):
    owner, source = queue_owner
    probe = Mock(return_value=_media(str(source), dv=dv, hdr=hdr, hdrplus=hdrplus))
    monkeypatch.setattr("dragontools.worker.queue_pipeline_preview.analyze_media", probe)
    owner.update_queue_label(str(source))
    assert "Analyse läuft" in owner.file_list.item(0).text()
    qtbot.waitUntil(lambda: f"[Encode: {label}]" in owner.file_list.item(0).text(), timeout=5000)
    probe.assert_called_once()


def test_queue_probe_keeps_ui_responsive_and_reuses_analysis_after_settings_change(queue_owner, qtbot, monkeypatch):
    owner, source = queue_owner
    entered, release, tick = Event(), Event(), []

    def analyze(*_, **_kwargs):
        entered.set()
        assert release.wait(5)
        return _media(str(source), dv=True, hdr=True, hdrplus=True)

    probe = Mock(side_effect=analyze)
    monkeypatch.setattr("dragontools.worker.queue_pipeline_preview.analyze_media", probe)
    owner.update_queue_label(str(source))
    try:
        qtbot.waitUntil(entered.is_set, timeout=3000)
        QTimer.singleShot(0, lambda: tick.append(True))
        qtbot.waitUntil(lambda: bool(tick), timeout=1000)
        owner.preserve_dv_cb.setChecked(False)
        owner.preserve_hdrplus_cb.setChecked(False)
    finally:
        release.set()
    qtbot.waitUntil(lambda: "[Encode: HDR]" in owner.file_list.item(0).text(), timeout=5000)
    owner.preserve_dv_cb.setChecked(True)
    qtbot.waitUntil(lambda: "[Encode: DV]" in owner.file_list.item(0).text(), timeout=5000)
    probe.assert_called_once()


def test_failed_queue_analysis_is_explicit_and_shutdown_does_not_restart(queue_owner, qtbot, monkeypatch):
    owner, source = queue_owner
    monkeypatch.setattr("dragontools.worker.queue_pipeline_preview.analyze_media", Mock(side_effect=OSError("missing tool")))
    owner.update_queue_label(str(source))
    qtbot.waitUntil(lambda: "Analyse fehlgeschlagen" in owner.file_list.item(0).text(), timeout=5000)
    owner._pipeline_preview.shutdown()
    owner.update_queue_label(str(source))
    assert "Standard" not in owner.file_list.item(0).text()
    assert not owner._pipeline_preview._pending


def test_queue_reanalyzes_changed_source_and_discards_late_result(queue_owner, qtbot, monkeypatch):
    owner, source = queue_owner
    entered, release = Event(), Event()

    def analyze(*_, **_kwargs):
        if not entered.is_set():
            entered.set()
            assert release.wait(5)
            return _media(str(source), dv=True, hdr=True)
        return _media(str(source), hdr=True)

    probe = Mock(side_effect=analyze)
    monkeypatch.setattr("dragontools.worker.queue_pipeline_preview.analyze_media", probe)
    owner.update_queue_label(str(source))
    try:
        qtbot.waitUntil(entered.is_set, timeout=3000)
        source.write_bytes(b"DIFFERENT SOURCE")
    finally:
        release.set()
    qtbot.waitUntil(lambda: "[Encode: HDR]" in owner.file_list.item(0).text(), timeout=5000)
    assert probe.call_count == 2


def test_queue_abort_retains_worker_until_finished_and_does_not_restart(queue_owner, qtbot, monkeypatch):
    owner, source = queue_owner
    entered, release = Event(), Event()

    def analyze(*_, **_kwargs):
        entered.set()
        assert release.wait(5)
        return _media(str(source), dv=True, hdr=True)

    monkeypatch.setattr("dragontools.worker.queue_pipeline_preview.analyze_media", Mock(side_effect=analyze))
    owner.update_queue_label(str(source))
    try:
        qtbot.waitUntil(entered.is_set, timeout=3000)
        worker, = owner._pipeline_preview.workers_for_shutdown()
        owner._pipeline_preview.shutdown()
        assert worker.abort_requested and worker.isRunning()
        assert owner._pipeline_preview.workers_for_shutdown() == (worker,)
        owner.preserve_dv_cb.setChecked(False)
        owner.update_queue_label(str(source))
    finally:
        release.set()
    qtbot.waitUntil(lambda: not owner._pipeline_preview.workers_for_shutdown(), timeout=5000)
    assert not owner._pipeline_preview._pending


def test_actual_preview_metadata_decisions_override_legacy_badge_fallback():
    owner = ConvertWidgetQueueBadgesMixin()
    preview = {"pipeline": "av1_dv", "video": {"has_dv": True, "has_hdr10plus": True},
               "dv_preserved": True, "hdr10plus_preserved": False, "effective_preserve_hdrplus": True}
    assert owner._encode_badge_label(preview) == "DV"


def test_queue_checks_generator_capability_in_owned_background_worker(queue_owner, qtbot, monkeypatch):
    from PyQt6.QtCore import QThread
    from dragontools.worker.queue_pipeline_preview import QueuePipelinePreviewWorker
    owner, source = queue_owner
    owner.extra_encoder_options = {"hdr10plus_generator_enabled": True, "_hdr10plus_generator_available": False}
    monkeypatch.setattr("dragontools.worker.queue_pipeline_preview.analyze_media", Mock(return_value=_media(str(source), hdr=True)))
    calls = []

    def available(worker):
        assert QThread.currentThread() is worker
        calls.append(True)
        return True

    monkeypatch.setattr(QueuePipelinePreviewWorker, "_generator_available", available)
    owner.update_queue_label(str(source))
    assert calls == []
    qtbot.waitUntil(lambda: "[Encode: HDR10+]" in owner.file_list.item(0).text(), timeout=5000)
    assert calls == [True]


def test_queue_does_not_label_missing_video_as_standard(queue_owner, qtbot, monkeypatch):
    owner, source = queue_owner
    monkeypatch.setattr("dragontools.worker.queue_pipeline_preview.analyze_media", Mock(return_value=MediaInfo(str(source), [], [], [])))
    owner.update_queue_label(str(source))
    qtbot.waitUntil(lambda: "Analyse fehlgeschlagen" in owner.file_list.item(0).text(), timeout=5000)
