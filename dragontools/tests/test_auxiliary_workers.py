# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from dragontools.core.models import MediaInfo, VideoStream


def _qt_core_stub_modules() -> dict[str, ModuleType]:
    qt_pkg = ModuleType("PyQt6")
    qt_core = ModuleType("PyQt6.QtCore")

    class _QThread:
        def __init__(self, parent=None):
            self._parent = parent

    class _Signal:
        def connect(self, *args, **kwargs):
            return None

        def emit(self, *args, **kwargs):
            return None

    def _pyqt_signal(*args, **kwargs):
        return _Signal()

    class _QSettings:
        def __init__(self, *args, **kwargs):
            pass
        def value(self, key, default=None, type=None):
            return default
        def setValue(self, *args, **kwargs):
            return None

    qt_core.QThread = _QThread
    qt_core.pyqtSignal = _pyqt_signal
    qt_core.QSettings = _QSettings
    qt_pkg.QtCore = qt_core
    return {"PyQt6": qt_pkg, "PyQt6.QtCore": qt_core}


def _reload_module(name: str):
    sys.modules.pop(name, None)
    return importlib.import_module(name)


def _fake_tools():
    return SimpleNamespace(
        ffmpeg="ffmpeg",
        ffprobe="ffprobe",
        makemkvcon="makemkvcon",
        mkvmerge="mkvmerge",
    )


def _fake_logger():
    def noop(*args, **kwargs):
        return None

    return SimpleNamespace(
        log_file=None,
        info=noop,
        warn=noop,
        error=noop,
        success=noop,
        audio=noop,
        header=noop,
        file_start=noop,
        file_done=noop,
    )


def _iso_thread():
    with patch.dict(sys.modules, _qt_core_stub_modules()):
        iso_mod = _reload_module("dragontools.worker.iso_thread")
    with patch.object(iso_mod, "create_worker_logger", return_value=_fake_logger()):
        return iso_mod.ISOThread(inputs=[], tools=_fake_tools())


def _mp4_thread():
    with patch.dict(sys.modules, _qt_core_stub_modules()):
        mp4_mod = _reload_module("dragontools.worker.mp4_remux_thread")
    with patch.object(mp4_mod, "create_worker_logger", return_value=_fake_logger()):
        return mp4_mod.MP4RemuxThread(files=[], tools=_fake_tools())

def _dv_remux_thread(files=None, *, overwrite_original=False):
    with patch.dict(sys.modules, _qt_core_stub_modules()):
        dv_mod = _reload_module("dragontools.worker.dv_remux_thread")
    with patch.object(dv_mod, "create_worker_logger", return_value=_fake_logger()):
        thread = dv_mod.DVRemuxThread(
            files=list(files or []),
            overwrite_original=overwrite_original,
        )
    return thread


def test_iso_makemkv_source_uses_iso_and_file_prefixes():
    thread = _iso_thread()
    assert thread._makemkv_source("Film.iso") == "iso:Film.iso"
    assert thread._makemkv_source("BDMV_FOLDER") == "file:BDMV_FOLDER"


def test_iso_makemkv_source_uses_disc_root_for_direct_bdmv_folder(tmp_path):
    thread = _iso_thread()
    disc_root = tmp_path / "Disc"
    bdmv = disc_root / "BDMV"
    bdmv.mkdir(parents=True)

    assert thread._makemkv_source(str(bdmv)) == f"file:{disc_root}"


def test_iso_detects_direct_bdmv_and_video_ts_folders(tmp_path):
    thread = _iso_thread()
    bdmv = tmp_path / "Film" / "BDMV"
    bdmv.mkdir(parents=True)
    (bdmv / "index.bdmv").write_text("", encoding="utf-8")
    video_ts = tmp_path / "DVD" / "VIDEO_TS"
    video_ts.mkdir(parents=True)
    (video_ts / "VTS_01_1.VOB").write_bytes(b"vob")

    assert thread._detect_iso_type(str(bdmv)) == "bluray"
    assert thread._detect_iso_type(str(video_ts)) == "dvd"


def test_iso_extracts_multiple_titles_as_single_makemkv_calls(tmp_path):
    thread = _iso_thread()
    thread._extracted_files = []
    calls: list[list[str]] = []

    def fake_run(args, progress_path=None):
        calls.append(args)
        return 0, []

    thread._run_makemkv = fake_run
    assert thread._extract_titles("Film.iso", [1, 2], str(tmp_path))

    assert calls[0] == ["-r", "--cache=1", "mkv", "iso:Film.iso", "1", str(tmp_path)]
    assert calls[1] == ["-r", "--cache=1", "mkv", "iso:Film.iso", "2", str(tmp_path)]


def test_iso_scan_reports_outdated_makemkv():
    thread = _iso_thread()

    def fake_run(args, progress_path=None):
        return 1, [
            'MSG:5021,131332,1,"Diese Programmversion ist zu alt. Bitte laden Sie die aktuelle Version herunter."'
        ]

    thread._run_makemkv = fake_run

    assert thread._scan_titles("Film.iso") == []
    assert "MakeMKV ist zu alt" in thread._last_scan_error


def test_iso_ffmpeg_fallback_detects_largest_bluray_stream(tmp_path):
    thread = _iso_thread()
    stream_dir = tmp_path / "BDMV" / "STREAM"
    stream_dir.mkdir(parents=True)
    small = stream_dir / "00001.m2ts"
    large = stream_dir / "00002.m2ts"
    small.write_bytes(b"1" * 10)
    large.write_bytes(b"2" * 30)

    candidate = thread._ffmpeg_fallback_candidate(str(tmp_path))

    assert candidate["mode"] == "file"
    assert candidate["path"] == large
    assert candidate["label"] == "Blu-ray-Stream 00002.m2ts"


def test_iso_ffmpeg_fallback_detects_largest_dvd_vob_group(tmp_path):
    thread = _iso_thread()
    dvd_dir = tmp_path / "VIDEO_TS"
    dvd_dir.mkdir()
    (dvd_dir / "VTS_01_0.VOB").write_bytes(b"menu")
    (dvd_dir / "VTS_01_1.VOB").write_bytes(b"1" * 10)
    (dvd_dir / "VTS_01_2.VOB").write_bytes(b"2" * 10)
    (dvd_dir / "VTS_02_1.VOB").write_bytes(b"3" * 30)

    candidate = thread._ffmpeg_fallback_candidate(str(tmp_path))

    assert candidate["mode"] == "concat"
    assert [p.name for p in candidate["files"]] == ["VTS_02_1.VOB"]
    assert candidate["label"] == "DVD-VOB-Titelgruppe VTS_02"


def test_iso_process_uses_ffmpeg_fallback_when_makemkv_scan_has_no_titles(tmp_path):
    thread = _iso_thread()
    iso = tmp_path / "Film.iso"
    iso.write_bytes(b"iso")
    out = tmp_path / "out"
    calls: list[tuple[str, str]] = []

    thread._scan_titles = lambda path: []

    def fake_fallback(path, output_dir):
        calls.append((path, output_dir))
        return True

    thread._extract_with_ffmpeg_fallback = fake_fallback

    thread._process_input(str(iso), total=1)

    assert calls == [(str(iso), str(iso.parent))]


def test_mp4_remux_rejects_dolby_vision():
    thread = _mp4_thread()
    mi = MediaInfo(
        path="Film.mkv",
        audio_streams=[],
        subtitle_streams=[],
        video_streams=[VideoStream(index=0, codec="hevc", width=3840, height=2160, hdr_format="dolby_vision")],
        dolby_vision=True,
        dolby_vision_profile="7",
    )

    ok, reason = thread._is_mp4_video_compatible(mi)
    assert not ok
    assert "Dolby Vision" in reason


def test_mp4_remux_rejects_hdr10plus():
    thread = _mp4_thread()
    mi = MediaInfo(
        path="Film.mkv",
        audio_streams=[],
        subtitle_streams=[],
        video_streams=[VideoStream(index=0, codec="hevc", width=3840, height=2160, hdr_format="hdr10plus")],
        has_hdr10plus=True,
    )

    ok, reason = thread._is_mp4_video_compatible(mi)
    assert not ok
    assert "HDR10+" in reason


def test_mp4_remux_allows_plain_hevc():
    thread = _mp4_thread()
    mi = MediaInfo(
        path="Film.mkv",
        audio_streams=[],
        subtitle_streams=[],
        video_streams=[VideoStream(index=0, codec="hevc", width=1920, height=1080)],
    )

    ok, reason = thread._is_mp4_video_compatible(mi)
    assert ok
    assert reason == "hevc"


def test_subtitle_injector_uses_configured_mkvmerge_path(tmp_path):
    from dragontools.subtitle.injector import inject_with_mkvmerge

    out = tmp_path / "Film_sub.mkv"

    def fake_run(cmd, *args, **kwargs):
        out.write_bytes(b"OK")
        return SimpleNamespace(ok=True, returncode=0, stdout="", stderr="")

    with (
        patch("dragontools.subtitle.injector.get_timeout", return_value=30),
        patch("dragontools.subtitle.injector.run_tool", side_effect=fake_run) as mock_run,
    ):
        assert inject_with_mkvmerge(
            "Film.mkv",
            "Film.de.srt",
            str(out),
            mkvmerge="C:/Tools/mkvmerge.exe",
        )

    assert mock_run.call_args.args[0][0] == "C:/Tools/mkvmerge.exe"


def test_subtitle_injector_mp4_text_mode_maps_only_video_audio_and_new_subtitle(tmp_path):
    from dragontools.subtitle.injector import inject_with_ffmpeg

    out = tmp_path / "Film_sub.mp4"

    def fake_run(cmd, *args, **kwargs):
        out.write_bytes(b"OK")
        return SimpleNamespace(ok=True, returncode=0, stdout="", stderr="")

    with (
        patch("dragontools.subtitle.injector.get_timeout", return_value=30),
        patch("dragontools.subtitle.injector.run_tool", side_effect=fake_run) as mock_run,
    ):
        assert inject_with_ffmpeg(
            "Film.mp4",
            "Film.de.srt",
            str(out),
            ffmpeg="C:/Tools/ffmpeg.exe",
            subtitle_codec="mov_text",
            map_existing_subtitles=False,
        )

    cmd = mock_run.call_args.args[0]
    assert cmd[0] == "C:/Tools/ffmpeg.exe"
    assert "0:v?" in cmd
    assert "0:a?" in cmd
    assert "1:0" in cmd
    assert cmd[cmd.index("-c:s") + 1] == "mov_text"


def test_subtitle_extract_with_ffmpeg_accepts_codec_args(tmp_path):
    from dragontools.subtitle.extractor import extract_with_ffmpeg

    out = tmp_path / "Film.de.srt"

    def fake_run(cmd, *args, **kwargs):
        out.write_bytes(b"OK")
        return SimpleNamespace(ok=True, returncode=0, stdout="", stderr="")

    with (
        patch("dragontools.subtitle.extractor.get_timeout", return_value=30),
        patch("dragontools.subtitle.extractor.run_tool", side_effect=fake_run) as mock_run,
    ):
        assert extract_with_ffmpeg(
            "Film.mkv",
            3,
            str(out),
            ffmpeg="ffmpeg",
            codec_args=["-c:s", "srt"],
        )

    cmd = mock_run.call_args.args[0]
    assert cmd[cmd.index("-c:s") + 1] == "srt"


def test_subtitle_to_txt_supports_ass(tmp_path):
    from dragontools.subtitle.converter import subtitle_to_txt

    ass = tmp_path / "Film.ass"
    ass.write_text(
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,Hallo\\NWelt\n",
        encoding="utf-8",
    )

    assert subtitle_to_txt(ass) == (
        "00:00:01,000 --> 00:00:02,000\n"
        "Hallo\n"
        "Welt"
    )



def test_mp4_overwrite_exportiert_sidecars_vor_original_replace(tmp_path, monkeypatch):
    from dragontools.worker.subtitle_sidecar_service import SubtitleExportResult

    thread = _mp4_thread()
    messages = []
    thread._log = lambda message, *_args: messages.append(str(message))
    # Der Helfer laedt MP4-Module unter Qt-Stubs neu. Das persistente Journal
    # ist hier nicht Testgegenstand und darf keine Benutzerdaten beschreiben.
    class TestJournal:
        @classmethod
        def start(cls, **_kwargs):
            return cls()

        def set_status(self, *_args, **_kwargs):
            return None

        def finish(self):
            return None

    service_globals = thread._sidecar_service().commit.__func__.__globals__
    monkeypatch.setitem(service_globals, "SidecarJournal", TestJournal)
    file_service = thread._remux_file.__globals__["MP4RemuxFileService"]
    replace_function = file_service.remux.__globals__["commit_staged_output"]
    monkeypatch.setitem(replace_function.__globals__, "ReplaceJournal", TestJournal)
    source = tmp_path / "Film.mp4"
    source.write_bytes(b"ORIGINAL-MP4")
    old_sidecar = tmp_path / "Film.de.srt"
    old_sidecar.write_text("USER-SUBTITLE", encoding="utf-8")

    thread.files = [str(source)]
    thread.overwrite_original = True
    thread.export_subtitles = True
    thread.ignore_subtitles = False
    mi = SimpleNamespace(
        primary_video=SimpleNamespace(codec="h264"),
        dolby_vision=False,
        dolby_vision_profile=None,
        has_dv=False,
        has_hdr10plus=False,
        has_hdrplus=False,
        audio_streams=[],
        subtitle_streams=[],
        analysis_warnings=[],
        analysis_source="test",
        duration_s=1.0,
    )

    def fake_ffmpeg(cmd, duration_s, input_path):
        Path(cmd[-1]).write_bytes(b"NEW-MP4")
        return 0

    def fake_export(input_path, out_base, media_info=None):
        # Kernregression: zu diesem Zeitpunkt muss die Quelle noch ORIGINAL sein.
        assert Path(input_path).read_bytes() == b"ORIGINAL-MP4"
        staged = Path(str(out_base) + ".de.srt")
        staged.write_text("NEW-SUBTITLE", encoding="utf-8")
        return SubtitleExportResult(
            planned_stream_indices=(3,),
            exported_paths=(str(staged),),
        )

    thread._run_ffmpeg_with_progress = fake_ffmpeg
    thread._extract_external_subtitles = fake_export
    # _mp4_thread() lädt das Modul unter Qt-Stubs neu. patch() über sys.modules
    # kann danach die wiederhergestellte alte Modulinstanz treffen; die Methode
    # selbst besitzt jedoch weiterhin das korrekte Globals-Dictionary.
    with patch.dict(thread._remux_file.__globals__, {"analyze_media": lambda *_args: mi}):
        ok = thread._remux_file(str(source), str(source))

    assert ok is True, messages
    assert source.read_bytes() == b"NEW-MP4"
    assert old_sidecar.read_text(encoding="utf-8") == "NEW-SUBTITLE"
    backups = list(tmp_path.glob("Film.de.srt.dragontools_backup*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "USER-SUBTITLE"


def test_mp4_overwrite_blockiert_replace_wenn_sidecar_export_fehlschlaegt(tmp_path):
    from dragontools.worker.subtitle_sidecar_service import (
        SubtitleExportFailure,
        SubtitleExportResult,
    )

    thread = _mp4_thread()
    source = tmp_path / "Film.mp4"
    source.write_bytes(b"ORIGINAL-MP4")
    thread.files = [str(source)]
    thread.overwrite_original = True
    thread.export_subtitles = True
    thread.ignore_subtitles = False
    mi = SimpleNamespace(
        primary_video=SimpleNamespace(codec="h264"),
        dolby_vision=False,
        dolby_vision_profile=None,
        has_dv=False,
        has_hdr10plus=False,
        has_hdrplus=False,
        audio_streams=[],
        subtitle_streams=[],
        analysis_warnings=[],
        analysis_source="test",
        duration_s=1.0,
    )

    def fake_ffmpeg(cmd, duration_s, input_path):
        Path(cmd[-1]).write_bytes(b"NEW-MP4")
        return 0

    thread._run_ffmpeg_with_progress = fake_ffmpeg
    thread._extract_external_subtitles = lambda *args, **kwargs: SubtitleExportResult(
        planned_stream_indices=(3,),
        failures=(SubtitleExportFailure(3, "de", "subrip", "rc=1"),),
    )
    module = thread.__class__.__module__
    with patch(f"{module}.analyze_media", return_value=mi):
        ok = thread._remux_file(str(source), str(source))

    assert ok is False
    assert source.read_bytes() == b"ORIGINAL-MP4"
    assert not (tmp_path / "Film.__mp4_remux_tmp__.mp4").exists()



def test_dv_remux_exportiert_sidecars_vor_container_replace(tmp_path, monkeypatch):
    from dragontools.worker.subtitle_sidecar_service import SubtitleExportResult
    from dragontools.core import sidecar_journal

    monkeypatch.setattr(sidecar_journal, "app_documents_dir", lambda _root=None: tmp_path)

    source = tmp_path / "Film.mkv"
    source.write_bytes(b"ORIGINAL-DV")
    temp_output = tmp_path / "temp.mp4"
    final_output = tmp_path / "Film.mp4"
    thread = _dv_remux_thread([str(source)], overwrite_original=True)
    thread._prepare_remux_metadata = lambda path: (
        "Film",
        SimpleNamespace(),
        1000,
        {},
    )
    thread._emit_remux_success = lambda *args, **kwargs: None

    class Pipeline:
        def run(self, **kwargs):
            Path(kwargs["output_path"]).write_bytes(b"NEW-DV-MP4")
            return True

    export_seen = {"done": False}

    class SubtitleService:
        def export_sidecars_result(self, **kwargs):
            # Die MKV-Quelle darf noch nicht entfernt worden sein.
            assert source.exists()
            assert source.read_bytes() == b"ORIGINAL-DV"
            staged = Path(str(Path(kwargs["output_base"])) + ".de.srt")
            staged.write_text("DV-SUB", encoding="utf-8")
            export_seen["done"] = True
            return SubtitleExportResult(
                planned_stream_indices=(3,),
                exported_paths=(str(staged),),
            )

    class OutputManager:
        def build_output_path(self, input_path):
            return str(temp_output)
        def replace_output_if_needed(self, input_path, output_path):
            assert export_seen["done"] is True
            source.unlink()
            Path(output_path).replace(final_output)
            return True, str(final_output)
        def cleanup_incomplete(self, input_path, output_path):
            return None

    thread._mp4box_pipeline = Pipeline()
    thread._subtitle_service = SubtitleService()
    thread._output_manager = OutputManager()

    assert thread._remux_file_safe(str(source)) is True
    assert final_output.read_bytes() == b"NEW-DV-MP4"
    assert (tmp_path / "Film.de.srt").read_text(encoding="utf-8") == "DV-SUB"
