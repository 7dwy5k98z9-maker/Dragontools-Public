from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from dragontools.core.models import SubtitleStream
from dragontools.rules.subtitle_rule_config import migrate_subtitle_rules
from dragontools.worker import bitmap_subtitle_ocr_service as ocr_module
from dragontools.worker import dv_subtitle_mux_service as dv_subs
from dragontools.worker.converter_subtitle_args import _mkv_args
from dragontools.worker.subtitle_sidecar_service import SubtitleSidecarService


def _sub(index: int, codec: str = "hdmv_pgs_subtitle", language: str = "de"):
    return SubtitleStream(index=index, language=language, forced=False, title="Deutsch", codec=codec)


def test_subtitle_rule_migration_adds_pgs_controls():
    rules = migrate_subtitle_rules({})
    assert rules["pgs_to_srt_enabled"] is False
    assert rules["pgs_original_storage"] == "internal_mkv"


def test_normal_mkv_keeps_pgs_internal_by_default_and_can_switch_to_sidecar():
    pgs = _sub(9)
    logger = SimpleNamespace(decision=lambda *_: None)
    worker = SimpleNamespace(_logger=logger)

    _burn, default_args = _mkv_args(worker, None, [pgs], subtitle_rules={"pgs_original_storage": "internal_mkv"})
    assert "0:9" in default_args
    assert "copy" in default_args

    _burn, sidecar_args = _mkv_args(worker, None, [pgs], subtitle_rules={"pgs_original_storage": "sidecar"})
    assert sidecar_args == ["-sn"]


def test_dv_mkv_pgs_is_preserved_directly_without_ffmpeg_sup_extraction(tmp_path):
    source = tmp_path / "source.mkv"
    source.write_bytes(b"source")
    pgs = _sub(9)
    plan = SimpleNamespace(keep_streams=(pgs,), burn_sub=None, burn_warnings=())
    service = dv_subs.DVSubtitleMuxService(
        ffmpeg_path="ffmpeg",
        subtitle_rules={"pgs_original_storage": "internal_mkv"},
        log=lambda *_: None,
    )
    service.build_internal_jobs = lambda *_args, **_kwargs: [
        dv_subs.DVSubtitleJob(9, "hdmv_pgs_subtitle", ".sup", ("-c:s", "copy"), "de", "Deutsch", False)
    ]
    calls = []
    ok, tracks = service.prepare_internal_mkv_tracks(
        input_path=str(source), media_info=SimpleNamespace(subtitle_streams=[pgs]),
        file_override=None, tmp_dir=tmp_path, run_fn=lambda cmd: calls.append(cmd) or 1,
    )
    assert ok is True
    assert calls == []
    assert len(tracks) == 1
    assert tracks[0].source_direct is True
    assert tracks[0].path == source


def test_pgs_ocr_failure_is_warning_only_and_does_not_fail_sidecar_result(monkeypatch, tmp_path):
    source = tmp_path / "source.mkv"
    source.write_bytes(b"source")
    pgs = _sub(9)
    mi = SimpleNamespace(subtitle_streams=[pgs], audio_streams=[], duration_s=60.0)
    worker = SimpleNamespace(
        settings=SimpleNamespace(value=lambda *_args, **_kwargs: None),
        tools=SimpleNamespace(ffmpeg="ffmpeg", ffprobe="ffprobe", tesseract="tesseract"),
        abort_requested=False,
    )
    logs = []
    service = SubtitleSidecarService(
        ffmpeg_path="ffmpeg",
        subtitle_rules={
            "language_priority": ["de"], "max_languages": 1, "tracks_per_language": 1,
            "keep_rules": {"keep_selected_languages": True, "keep_regular": True, "keep_forced": True},
            "pgs_to_srt_enabled": True,
            "pgs_original_storage": "internal_mkv",
            "additional_sidecars_enabled": False,
            "mp4_sidecars_enabled": False,
        },
        log=lambda msg, level="info": logs.append((level, msg)),
        worker=worker,
    )
    monkeypatch.setattr(
        ocr_module.BitmapSubtitleOcrService,
        "create_srt",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("Not enough data, skipping 8910 bytes")),
    )
    result = service.export_sidecars_result(
        input_path=str(source), output_base=tmp_path / "Film", media_info=mi, container="mkv"
    )
    assert result.complete is True
    assert result.failures == ()
    assert any("PGS→SRT" in msg and "übersprungen" in msg for _level, msg in logs)
    assert any("Original-PGS" in msg for _level, msg in logs)


def test_watchfolder_cleanup_is_bound_to_finished_thread_source():
    source = Path("dragontools/gui/watch_folder_controller.py").read_text(encoding="utf-8")
    assert "thread.finished.connect(lambda t=thread: self._thread_finished(t))" in source
    assert "if thread is self._thread:" in source


def test_pgs_ocr_success_is_optional_extra_and_result_stays_complete(monkeypatch, tmp_path):
    source = tmp_path / "source.mkv"
    source.write_bytes(b"source")
    pgs = _sub(9)
    mi = SimpleNamespace(subtitle_streams=[pgs], audio_streams=[], duration_s=60.0)
    worker = SimpleNamespace(
        settings=SimpleNamespace(value=lambda *_args, **_kwargs: None),
        tools=SimpleNamespace(ffmpeg="ffmpeg", ffprobe="ffprobe", tesseract="tesseract"),
        abort_requested=False,
    )
    service = SubtitleSidecarService(
        ffmpeg_path="ffmpeg",
        subtitle_rules={
            "language_priority": ["de"], "max_languages": 1, "tracks_per_language": 1,
            "keep_rules": {"keep_selected_languages": True, "keep_regular": True, "keep_forced": True},
            "pgs_to_srt_enabled": True, "pgs_original_storage": "internal_mkv",
            "additional_sidecars_enabled": False, "mp4_sidecars_enabled": False,
        },
        log=lambda *_args, **_kwargs: None, worker=worker,
    )
    def fake_create(_self, _issue, target):
        target = Path(target)
        target.write_text("1\n00:00:00,000 --> 00:00:01,000\nTest\n", encoding="utf-8")
        return target
    monkeypatch.setattr(ocr_module.BitmapSubtitleOcrService, "create_srt", fake_create)
    result = service.export_sidecars_result(
        input_path=str(source), output_base=tmp_path / "Film", media_info=mi, container="mkv"
    )
    assert result.complete is True
    assert len(result.exported_paths) == 1
    assert result.exported_paths[0].endswith(".de.srt")


def test_dv_mkv_source_direct_pgs_uses_source_track_without_sup_file(tmp_path):
    from dragontools.worker.dv_remux_muxers import DVRemuxMuxer

    video = tmp_path / "video.hevc"
    source = tmp_path / "source.mkv"
    output = tmp_path / "out.mkv"
    video.write_bytes(b"video")
    source.write_bytes(b"source")
    seen = {}

    class Runner:
        def run_abortable_capture(self, cmd, *, timeout_s=None):
            seen["cmd"] = list(cmd)
            output.write_bytes(b"mkv")
            return 0, "", ""

    worker = SimpleNamespace(
        container="mkv", tools=SimpleNamespace(mkvmerge="mkvmerge", mp4box="MP4Box"),
        abort_requested=False, _last_stderr="", log=lambda *_args, **_kwargs: None,
    )
    muxer = DVRemuxMuxer(worker, Runner())
    track = dv_subs.DVMuxSubtitleTrack(
        path=source, stream_index=9, codec="hdmv_pgs_subtitle", language="de",
        title="Deutsch PGS", forced=False, source_direct=True,
    )
    assert muxer.mux_mkv(str(video), [], str(output), [track]) is True
    cmd = seen["cmd"]
    assert "--subtitle-tracks" in cmd
    assert "9" in cmd
    assert str(source) in cmd
    assert not any(str(part).endswith(".sup") for part in cmd)
