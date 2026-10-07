from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


class _Signal:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


class _Logger:
    def file_start(self, *args, **kwargs):
        pass

    def file_done(self, *args, **kwargs):
        pass


def _merge_info(*, sample_rate=48000, transfer="bt709"):
    return {
        "path": "a.mkv",
        "container": "mkv",
        "video_codec": "hevc",
        "width": 1920,
        "height": 1080,
        "fps": 24.0,
        "duration_s": 60.0,
        "chapter_count": 0,
        "dynamic_hdr": {"hdr_format": "", "hdr10plus": False, "dolby_vision": False, "dv_profile": 0},
        "video_structure": [{
            "codec": "hevc", "profile": "main 10", "codec_tag": "",
            "width": 1920, "height": 1080, "pix_fmt": "yuv420p10le",
            "sample_aspect_ratio": "1:1", "field_order": "progressive",
            "color_space": "bt2020nc", "color_transfer": transfer,
            "color_primaries": "bt2020" if transfer == "smpte2084" else "bt709",
        }],
        "audio_structure": [{
            "codec": "aac", "profile": "lc", "sample_rate": sample_rate,
            "channels": 2, "channel_layout": "stereo", "language": "deu",
            "title": "Deutsch AAC Stereo", "default": True, "forced": False,
        }],
        "subtitle_structure": [{
            "codec": "subrip", "language": "deu", "title": "Deutsch",
            "forced": False, "default": True,
        }],
    }


def test_merge_rejects_audio_sample_rate_mismatch():
    from dragontools.worker.merge_plan import MergePlanMixin

    first = _merge_info(sample_rate=48000)
    second = _merge_info(sample_rate=44100)
    ok, reasons = MergePlanMixin()._check_lossless_merge_possible([first, second], "mkv")
    assert not ok
    assert any("Audio-Struktur" in reason for reason in reasons)


def test_merge_rejects_hdr_color_header_mismatch():
    from dragontools.worker.merge_plan import MergePlanMixin

    first = _merge_info(transfer="bt709")
    second = _merge_info(transfer="smpte2084")
    ok, reasons = MergePlanMixin()._check_lossless_merge_possible([first, second], "mkv")
    assert not ok
    assert any("Video-Track-Struktur" in reason for reason in reasons)


def test_merge_abort_after_verification_never_publishes(tmp_path):
    from dragontools.worker import merge_executor as module
    from dragontools.worker.merge_common import MergeUserAbortError
    from dragontools.worker.merge_executor import MergeExecutorMixin

    output = tmp_path / "merged.mkv"

    class Host(MergeExecutorMixin):
        abort_requested = False
        tools = SimpleNamespace(mkvmerge="mkvmerge", ffprobe="ffprobe")
        _logger = _Logger()
        progress = _Signal()
        file_progress = _Signal()

        def _log(self, *args, **kwargs):
            pass

        def _verify_merge_output(self, path, infos):
            self.abort_requested = True
            return True

    host = Host()

    def fake_run(command, **kwargs):
        Path(command[command.index("-o") + 1]).write_bytes(b"x" * 2048)
        return SimpleNamespace(aborted=False, timed_out=False, ok=True, returncode=0)

    with patch.object(module, "run_tool", side_effect=fake_run):
        with pytest.raises(MergeUserAbortError):
            host._merge_mkv_lossless([str(tmp_path / "a.mkv"), str(tmp_path / "b.mkv")], str(output), infos=[_merge_info()])
    assert not output.exists()


def test_merge_late_destination_collision_is_not_overwritten(tmp_path):
    from dragontools.worker import merge_executor as module
    from dragontools.worker.merge_executor import MergeExecutorMixin

    output = tmp_path / "merged.mkv"

    class Host(MergeExecutorMixin):
        abort_requested = False
        tools = SimpleNamespace(mkvmerge="mkvmerge", ffprobe="ffprobe")
        _logger = _Logger()
        progress = _Signal()
        file_progress = _Signal()

        def _log(self, *args, **kwargs):
            pass

        def _verify_merge_output(self, path, infos):
            output.write_bytes(b"OTHER_PROCESS")
            return True

    host = Host()

    def fake_run(command, **kwargs):
        Path(command[command.index("-o") + 1]).write_bytes(b"x" * 2048)
        return SimpleNamespace(aborted=False, timed_out=False, ok=True, returncode=0)

    with patch.object(module, "run_tool", side_effect=fake_run):
        assert not host._merge_mkv_lossless([str(tmp_path / "a.mkv"), str(tmp_path / "b.mkv")], str(output), infos=[_merge_info()])
    assert output.read_bytes() == b"OTHER_PROCESS"


def test_iso_rejects_stale_explicit_title_selection(tmp_path):
    from dragontools.worker.iso_input_processor import ISOInputProcessor

    path = str(tmp_path / "disc.iso")

    class Host:
        selected_titles = {path: [99]}
        auto_main_title = True
        file_result = _Signal()

        def log_message(self, *args, **kwargs):
            pass

    processor = ISOInputProcessor(Host())
    assert processor._select_titles(path, Path(path), [{"id": 1, "duration": 3600}]) is None
    assert Host.file_result.calls
    assert "nicht mehr gültig" in Host.file_result.calls[-1][2]


def test_iso_selected_title_failure_never_falls_back_to_unmapped_raw_stream(tmp_path):
    from dragontools.worker.iso_input_processor import ISOInputProcessor

    class Host:
        abort_requested = False
        ffmpeg_fallback = True
        file_result = _Signal()
        file_progress = _Signal()
        fallback_calls = 0

        def extract_titles(self, path, title_ids, output_dir):
            return False

        def extract_with_ffmpeg_fallback(self, path, output_dir):
            self.fallback_calls += 1
            return True

        def log_message(self, *args, **kwargs):
            pass

    host = Host()
    assert not ISOInputProcessor(host)._extract("disc.iso", [3], str(tmp_path))
    assert host.fallback_calls == 0
    assert host.file_result.calls[-1][1] is False


def test_makemkv_rc_zero_without_output_is_failure(tmp_path):
    from dragontools.worker.iso_makemkv_service import ISOMakeMKVService

    inspector = SimpleNamespace(makemkv_source=lambda path: f"iso:{path}")
    service = ISOMakeMKVService(
        tools=SimpleNamespace(ffprobe="/usr/bin/ffprobe"),
        inspector=inspector,
        worker=SimpleNamespace(),
        log=lambda *args: None,
        progress=lambda *args: None,
    )
    result = service.extract_titles(
        "disc.iso", [1], str(tmp_path),
        run_makemkv=lambda args, progress_path=None: (0, []),
    )
    assert not result.ok
    assert "erzeugte aber nicht genau" in (result.error or "")


def test_mp4_subtitle_metadata_uses_mp4_language_and_both_dispositions():
    from dragontools.worker import mp4_remux_plan as module
    from dragontools.worker.mp4_remux_plan import MP4RemuxPlanner

    stream = SimpleNamespace(index=3, language="de", title="Forced", forced=True, default=True)
    storage = SimpleNamespace(internal_streams=[stream])
    planner = MP4RemuxPlanner(
        ffmpeg_path="ffmpeg", apply_audio_rules=False, export_subtitles=True,
        ignore_subtitles=False, subtitle_rules={}, faststart=False,
        log=lambda *args: None, log_audio=lambda *args, **kwargs: None,
    )
    media = SimpleNamespace(subtitle_streams=[stream], audio_streams=[], duration_s=60)
    with (
        patch.object(module, "compute_subtitle_plan", return_value=SimpleNamespace()),
        patch.object(module, "build_mp4_subtitle_storage_plan", return_value=storage),
    ):
        args, count = planner.build_subtitle_args_with_count(media)
    assert count == 1
    assert "language=deu" in args
    disp_idx = args.index("-disposition:s:0")
    assert args[disp_idx + 1] == "default+forced"


def test_mp4_planner_always_uses_private_staging(tmp_path):
    from dragontools.core.models import MediaInfo, VideoStream
    from dragontools.worker.mp4_remux_plan import MP4RemuxPlanner

    src = tmp_path / "in.mkv"
    dst = tmp_path / "out.mp4"
    media = MediaInfo(
        path=str(src), audio_streams=[], subtitle_streams=[],
        video_streams=[VideoStream(index=0, codec="h264", width=1920, height=1080, bit_depth=8)],
        duration_s=10.0,
    )
    planner = MP4RemuxPlanner(
        ffmpeg_path="ffmpeg", apply_audio_rules=False, export_subtitles=False,
        ignore_subtitles=True, subtitle_rules={}, faststart=False,
        log=lambda *args: None, log_audio=lambda *args, **kwargs: None,
    )
    plan = planner.build(str(src), str(dst), media)
    assert plan.staging != plan.destination
    assert plan.staging.suffix == ".mp4"
    assert plan.command[-1] == str(plan.staging)


def test_mp4_late_collision_preserves_other_file(tmp_path):
    from dragontools.worker.mp4_remux_file_service import MP4RemuxFileService
    from dragontools.worker.mp4_remux_plan import MP4RemuxPlan

    source = tmp_path / "source.mkv"
    source.write_bytes(b"SOURCE")
    destination = tmp_path / "source.mp4"
    staging = tmp_path / "source.__tmp__.mp4"
    plan = MP4RemuxPlan(
        source=source, destination=destination, staging=staging,
        command=("ffmpeg", str(staging)), duration_s=10.0, audio_plan=(),
        expected_audio_tracks=0, expected_subtitle_tracks=0,
    )

    class Planner:
        def build(self, *args):
            return plan

        def video_compatibility(self, media):
            return True, "h264"

    class Verifier:
        def verify(self, **kwargs):
            destination.write_bytes(b"OTHER")
            return SimpleNamespace(ok=True, messages=())

    results = []
    service = MP4RemuxFileService(
        planner=Planner(), logger=_Logger(), log=lambda *args: None,
        run_ffmpeg=lambda cmd, duration, path: (staging.write_bytes(b"x" * 2048), 0)[1],
        export_sidecars=lambda *args, **kwargs: None,
        commit_sidecars=lambda *args, **kwargs: None,
        cleanup_sidecars=lambda paths: None,
        abort_requested=lambda: False,
        emit_file_result=lambda *args: results.append(args),
        emit_file_progress=lambda *args: None,
        export_subtitles=False, ignore_subtitles=True,
        output_verifier=Verifier(),
    )
    media = SimpleNamespace(analysis_warnings=[], analysis_source="test")
    assert not service.remux(str(source), str(destination), media, current_index=1, total_files=1, user_abort_error=RuntimeError)
    assert destination.read_bytes() == b"OTHER"
    assert source.read_bytes() == b"SOURCE"


def test_mp4_new_destination_success_keeps_source(tmp_path):
    from dragontools.worker.mp4_remux_file_service import MP4RemuxFileService
    from dragontools.worker.mp4_remux_plan import MP4RemuxPlan

    source = tmp_path / "source.mkv"
    source.write_bytes(b"SOURCE")
    destination = tmp_path / "source.mp4"
    staging = tmp_path / "source.__tmp__.mp4"
    plan = MP4RemuxPlan(
        source=source, destination=destination, staging=staging,
        command=("ffmpeg", str(staging)), duration_s=10.0, audio_plan=(),
        expected_audio_tracks=0, expected_subtitle_tracks=0,
    )

    class Planner:
        def build(self, *args):
            return plan

        def video_compatibility(self, media):
            return True, "h264"

    class Verifier:
        def verify(self, **kwargs):
            return SimpleNamespace(ok=True, messages=())

    results = []
    service = MP4RemuxFileService(
        planner=Planner(), logger=_Logger(), log=lambda *args: None,
        run_ffmpeg=lambda cmd, duration, path: (staging.write_bytes(b"MP4" * 1024), 0)[1],
        export_sidecars=lambda *args, **kwargs: None,
        commit_sidecars=lambda *args, **kwargs: None,
        cleanup_sidecars=lambda paths: None,
        abort_requested=lambda: False,
        emit_file_result=lambda *args: results.append(args),
        emit_file_progress=lambda *args: None,
        export_subtitles=False, ignore_subtitles=True,
        output_verifier=Verifier(),
    )
    media = SimpleNamespace(analysis_warnings=[], analysis_source="test")
    assert service.remux(
        str(source), str(destination), media,
        current_index=1, total_files=1, user_abort_error=RuntimeError,
    )
    assert source.read_bytes() == b"SOURCE"
    assert destination.read_bytes() == b"MP4" * 1024
    assert not staging.exists()
    assert results[-1][1] is True


def test_mp4_verifier_rejects_missing_chapter():
    from dragontools.worker.mp4_remux_output_verifier import MP4RemuxOutputVerifier

    verifier = MP4RemuxOutputVerifier(ffprobe_path="ffprobe")
    verifier._verifier = SimpleNamespace(
        verify=lambda *args, **kwargs: SimpleNamespace(
            ok=True,
            messages=(),
            chapter_count=1,
            audio_stream_count=0,
            subtitle_stream_count=0,
        )
    )
    result = verifier.verify(
        output_path="out.mp4",
        expected_duration_ms=10_000,
        expected_audio_tracks=0,
        expected_subtitle_tracks=0,
        expected_chapter_count=2,
    )
    assert not result.ok
    assert any("Kapitel-Anzahl abweichend" in message for message in result.messages)


def test_merge_verifier_rejects_missing_chapter():
    from dragontools.worker.merge_output_verifier import MergeOutputVerifier

    verifier = MergeOutputVerifier(ffprobe_path="ffprobe")
    verifier._verifier = SimpleNamespace(
        verify=lambda *args, **kwargs: SimpleNamespace(
            ok=True,
            messages=(),
            chapter_count=2,
            video_stream_count=1,
            audio_stream_count=1,
            subtitle_stream_count=1,
        )
    )
    result = verifier.verify(
        output_path="out.mkv",
        expected_duration_ms=20_000,
        expected_video_tracks=1,
        expected_audio_tracks=1,
        expected_subtitle_tracks=1,
        expected_chapter_count=3,
    )
    assert not result.ok
    assert any("Kapitel-Anzahl abweichend" in message for message in result.messages)


def test_makemkv_partial_multi_title_failure_leaves_no_visible_outputs(tmp_path):
    from dragontools.worker.iso_makemkv_service import ISOMakeMKVService

    inspector = SimpleNamespace(makemkv_source=lambda path: f"iso:{path}")
    service = ISOMakeMKVService(
        tools=SimpleNamespace(ffprobe="/usr/bin/ffprobe"),
        inspector=inspector,
        worker=SimpleNamespace(),
        log=lambda *args: None,
        progress=lambda *args: None,
    )

    def fake_run(args, progress_path=None):
        title_id = int(args[4])
        stage_dir = Path(args[5])
        if title_id == 1:
            (stage_dir / "title01.mkv").write_bytes(b"partial" * 512)
            return 0, []
        return 2, ["simulated MakeMKV failure"]

    result = service.extract_titles("disc.iso", [1, 2], str(tmp_path), run_makemkv=fake_run)
    assert not result.ok
    assert not list(tmp_path.glob("*.mkv"))
    assert not any(path.name.startswith(".__dragontools_makemkv_") for path in tmp_path.iterdir())


def test_iso_ffmpeg_fallback_invalid_stage_is_never_published(tmp_path):
    from dragontools.worker import iso_ffmpeg_fallback_service as module
    from dragontools.worker.iso_ffmpeg_fallback_service import ISOFFmpegFallbackService

    source = tmp_path / "source.m2ts"
    source.write_bytes(b"source")
    inspector = SimpleNamespace(
        ffmpeg_fallback_candidate=lambda path: ({"mode": "file", "path": source, "size": 6, "label": "test"}, None),
        unique_fallback_output=lambda path, out_dir: Path(out_dir) / "fallback.mkv",
    )
    service = ISOFFmpegFallbackService(
        tools=SimpleNamespace(ffmpeg="/usr/bin/ffmpeg", ffprobe="/usr/bin/ffprobe"),
        inspector=inspector,
        worker=SimpleNamespace(),
        log=lambda *args: None,
        progress=lambda *args: None,
    )

    def fake_run(cmd, progress_path=None):
        Path(cmd[-1]).write_bytes(b"x" * 2048)
        return 0, []

    with (
        patch.object(service, "ensure_ffmpeg", return_value="ffmpeg"),
        patch.object(service, "_source_contract", return_value=(SimpleNamespace(audio_stream_count=0), 1000, 0)),
        patch.object(module.OutputVerifier, "verify", return_value=SimpleNamespace(ok=False, messages=("bad streams",))) as verify,
    ):
        result = service.extract(str(source), str(tmp_path), run_ffmpeg=fake_run)

    verify.assert_called_once()
    assert not result.ok
    assert not (tmp_path / "fallback.mkv").exists()
    assert not list(tmp_path.glob("*.__iso_ffmpeg_tmp__*.mkv"))


def test_merge_real_analysis_rejects_ffprobe_sample_rate_mismatch(tmp_path):
    from dragontools.worker import merge_analysis as module
    from dragontools.worker.merge_analysis import MergeAnalysisMixin
    from dragontools.worker.merge_plan import MergePlanMixin

    class Host(MergeAnalysisMixin):
        abort_requested = False
        tools = SimpleNamespace(ffprobe="ffprobe")
        file_progress = _Signal()
        progress = _Signal()

        def _log(self, *args, **kwargs):
            pass

        def _run_json_ffprobe(self, path):
            sample_rate = "48000" if str(path).endswith("a.mkv") else "44100"
            return {
                "format": {"format_name": "matroska,webm"},
                "streams": [
                    {
                        "index": 0,
                        "codec_type": "video",
                        "codec_name": "hevc",
                        "profile": "Main 10",
                        "width": 1920,
                        "height": 1080,
                        "pix_fmt": "yuv420p10le",
                        "sample_aspect_ratio": "1:1",
                        "field_order": "progressive",
                        "avg_frame_rate": "24/1",
                        "color_space": "bt709",
                        "color_transfer": "bt709",
                        "color_primaries": "bt709",
                        "disposition": {"attached_pic": 0},
                    },
                    {
                        "index": 1,
                        "codec_type": "audio",
                        "codec_name": "aac",
                        "profile": "LC",
                        "sample_rate": sample_rate,
                        "channels": 2,
                        "channel_layout": "stereo",
                        "tags": {"language": "deu", "title": "Deutsch"},
                        "disposition": {"default": 1, "forced": 0},
                    },
                ],
                "chapters": [],
            }

    primary = SimpleNamespace(codec="hevc", width=1920, height=1080, hdr_format="")
    audio = SimpleNamespace(codec="aac", channels=2, language="deu")
    media = SimpleNamespace(
        primary_video=primary,
        audio_streams=[audio],
        subtitle_streams=[],
        duration_s=60.0,
        analysis_warnings=[],
        has_hdrplus=False,
        has_dv=False,
        dv_profile_major=0,
    )
    with patch.object(module, "analyze_media", return_value=media):
        files = [tmp_path / "a.mkv", tmp_path / "b.mkv"]
        for path in files:
            path.write_bytes(b"SOURCE")
        infos = Host()._analyze_inputs([str(path) for path in files])
    ok, reasons = MergePlanMixin()._check_lossless_merge_possible(infos, "mkv")
    assert not ok
    assert any("Audio-Struktur" in reason for reason in reasons)


def test_mp4_actual_plan_late_collision_is_not_overwritten(tmp_path):
    from dragontools.core.models import MediaInfo, VideoStream
    from dragontools.worker.mp4_remux_file_service import MP4RemuxFileService
    from dragontools.worker.mp4_remux_plan import MP4RemuxPlanner

    source = tmp_path / "in.mkv"
    source.write_bytes(b"SOURCE")
    destination = tmp_path / "out.mp4"
    media = MediaInfo(
        path=str(source),
        audio_streams=[],
        subtitle_streams=[],
        video_streams=[VideoStream(index=0, codec="h264", width=1920, height=1080, bit_depth=8)],
        duration_s=10.0,
    )
    media.analysis_source = "test"
    media.analysis_warnings = []
    planner = MP4RemuxPlanner(
        ffmpeg_path="ffmpeg",
        apply_audio_rules=False,
        export_subtitles=False,
        ignore_subtitles=True,
        subtitle_rules={},
        faststart=False,
        log=lambda *args: None,
        log_audio=lambda *args, **kwargs: None,
    )

    def fake_run(cmd, duration, path):
        destination.write_bytes(b"OTHER_PROCESS")
        Path(cmd[-1]).write_bytes(b"REMUX" * 512)
        return 0

    class Verifier:
        def verify(self, **kwargs):
            return SimpleNamespace(ok=True, messages=())

    service = MP4RemuxFileService(
        planner=planner,
        logger=_Logger(),
        log=lambda *args: None,
        run_ffmpeg=fake_run,
        export_sidecars=lambda *args, **kwargs: None,
        commit_sidecars=lambda *args, **kwargs: None,
        cleanup_sidecars=lambda paths: None,
        abort_requested=lambda: False,
        emit_file_result=lambda *args: None,
        emit_file_progress=lambda *args: None,
        export_subtitles=False,
        ignore_subtitles=True,
        output_verifier=Verifier(),
    )
    assert not service.remux(
        str(source), str(destination), media,
        current_index=1, total_files=1, user_abort_error=RuntimeError,
    )
    assert destination.read_bytes() == b"OTHER_PROCESS"
    assert source.read_bytes() == b"SOURCE"


def test_merge_collision_after_last_precheck_cannot_overwrite(tmp_path):
    from dragontools.core.move_transaction import publish_staged_no_replace as real_publish
    from dragontools.worker import merge_executor as module
    from dragontools.worker.merge_executor import MergeExecutorMixin

    output = tmp_path / "merged.mkv"

    class Host(MergeExecutorMixin):
        abort_requested = False
        tools = SimpleNamespace(mkvmerge="mkvmerge", ffprobe="ffprobe")
        _logger = _Logger()
        progress = _Signal()
        file_progress = _Signal()

        def _log(self, *args, **kwargs):
            pass

        def _verify_merge_output(self, path, infos):
            return True

    host = Host()

    def fake_run(command, **kwargs):
        Path(command[command.index("-o") + 1]).write_bytes(b"MERGE" * 512)
        return SimpleNamespace(aborted=False, timed_out=False, ok=True, returncode=0)

    real_os_replace = __import__("os").replace

    def old_replace_with_race(src, dst):
        Path(dst).write_bytes(b"OTHER_PROCESS")
        return real_os_replace(src, dst)

    def new_publish_with_race(staging, destination):
        Path(destination).write_bytes(b"OTHER_PROCESS")
        return real_publish(staging, destination)

    with (
        patch.object(module, "run_tool", side_effect=fake_run),
        patch.object(module.os, "replace", side_effect=old_replace_with_race),
        patch.object(module, "publish_staged_no_replace", side_effect=new_publish_with_race, create=True),
    ):
        ok = host._merge_mkv_lossless(
            [str(tmp_path / "a.mkv"), str(tmp_path / "b.mkv")],
            str(output),
            infos=[_merge_info()],
        )

    assert not ok
    assert output.read_bytes() == b"OTHER_PROCESS"


def test_output_contract_rejects_audio_title_drift():
    from dragontools.worker.media_contract_types import ExpectedAudioTrack, ExpectedMediaContract
    from dragontools.worker.output_contract_tracks import compare_audio_tracks

    contract = ExpectedMediaContract(
        container="mp4",
        video_codec="h264",
        video_stream_count=1,
        audio_tracks=(ExpectedAudioTrack(codec="aac", channels=2, language="de", default=True, title="Deutsch AAC Stereo"),),
        subtitle_tracks=(),
    )
    actual = [{
        "codec_name": "aac",
        "channels": 2,
        "tags": {"language": "deu", "title": "Wrong title"},
        "disposition": {"default": 1},
    }]
    messages = compare_audio_tracks(contract, actual)
    assert any("Titel abweichend" in message for message in messages)
