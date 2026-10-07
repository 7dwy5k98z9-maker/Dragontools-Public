from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def _noop(*_args, **_kwargs):
    return None


def test_dv_remux_extract_video_pins_analyzed_primary_stream(tmp_path):
    from dragontools.worker.dv_remux_pipeline import DVRemuxPipelineRunner

    seen = {}
    class Runner:
        def run_cmd(self, cmd, *_args, **_kwargs):
            seen["cmd"] = list(cmd)
            Path(cmd[-1]).write_bytes(b"hevc")
            return 0

    worker = SimpleNamespace(
        tools=SimpleNamespace(ffmpeg="ffmpeg"),
        subtitle_rules={}, log=_noop, container="mkv",
    )
    pipeline = DVRemuxPipelineRunner(
        worker, Runner(),
        audio_plan_builder=lambda **_k: [],
        audio_title_builder=lambda **_k: "",
        audio_filter_builder=lambda _d: None,
    )
    media = SimpleNamespace(primary_video=SimpleNamespace(index=3))
    out = tmp_path / "video.hevc"
    assert pipeline.extract_video("source.mkv", str(out), 1000, media_info=media)
    cmd = seen["cmd"]
    assert cmd[cmd.index("-map") + 1] == "0:3"


def test_mov_text_mkv_preparation_reports_actual_subrip_codec(monkeypatch, tmp_path):
    import dragontools.worker.dv_subtitle_mux_service as module
    from dragontools.core.models import SubtitleStream

    stream = SubtitleStream(index=2, language="de", forced=False, title="Deutsch", codec="mov_text")
    monkeypatch.setattr(
        module,
        "compute_subtitle_plan",
        lambda *_a, **_k: SimpleNamespace(keep_streams=[stream], burn_sub=None, burn_warnings=()),
    )
    service = module.DVSubtitleMuxService(ffmpeg_path="ffmpeg", subtitle_rules={}, log=_noop)

    def run(cmd):
        Path(cmd[-1]).write_text("1\n00:00:00,000 --> 00:00:01,000\nTest\n", encoding="utf-8")
        return 0

    ok, tracks = service.prepare_internal_mkv_tracks(
        input_path="source.mp4",
        media_info=SimpleNamespace(subtitle_streams=[stream], audio_streams=[], duration_s=1.0),
        file_override=None,
        tmp_dir=tmp_path,
        run_fn=run,
    )
    assert ok is True
    assert len(tracks) == 1
    assert tracks[0].codec == "subrip"


def test_resolve_subtitle_ids_matches_metadata_not_inventory_order():
    from dragontools.worker.dv_mkv_source_subtitles import resolve_subtitle_ids

    ffprobe_payload = {
        "streams": [
            {"index": 3, "codec_name": "hdmv_pgs_subtitle", "tags": {"language": "deu", "title": "Deutsch Forced"}, "disposition": {"forced": 1, "default": 0}},
            {"index": 5, "codec_name": "subrip", "tags": {"language": "eng", "title": "English"}, "disposition": {"forced": 0, "default": 1}},
        ]
    }
    mkv_payload = {
        "tracks": [
            {"type": "subtitles", "id": 12, "codec": "SubRip/SRT", "properties": {"language": "eng", "track_name": "English", "forced_track": False, "default_track": True}},
            {"type": "subtitles", "id": 9, "codec": "HDMV PGS subtitles", "properties": {"language": "deu", "track_name": "Deutsch Forced", "forced_track": True, "default_track": False}},
        ]
    }

    def capture(command):
        payload = ffprobe_payload if "-select_streams" in command else mkv_payload
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), aborted=False, timed_out=False)

    mapping = resolve_subtitle_ids(path="source.mkv", ffprobe="ffprobe", mkvmerge="mkvmerge", capture=capture)
    assert mapping == {3: 9, 5: 12}


def test_resolve_subtitle_ids_fails_closed_for_ambiguous_identical_tracks():
    from dragontools.worker.dv_mkv_source_subtitles import resolve_subtitle_ids

    ffprobe_payload = {
        "streams": [
            {"index": 3, "codec_name": "hdmv_pgs_subtitle", "tags": {"language": "deu"}, "disposition": {"forced": 0, "default": 0}},
            {"index": 5, "codec_name": "hdmv_pgs_subtitle", "tags": {"language": "deu"}, "disposition": {"forced": 0, "default": 0}},
        ]
    }
    mkv_payload = {
        "tracks": [
            {"type": "subtitles", "id": 9, "codec": "HDMV PGS subtitles", "properties": {"language": "deu", "forced_track": False, "default_track": False}},
            {"type": "subtitles", "id": 12, "codec": "HDMV PGS subtitles", "properties": {"language": "deu", "forced_track": False, "default_track": False}},
        ]
    }

    def capture(command):
        payload = ffprobe_payload if "-select_streams" in command else mkv_payload
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), aborted=False, timed_out=False)

    with pytest.raises(ValueError, match="mehrdeutig"):
        resolve_subtitle_ids(path="source.mkv", ffprobe="ffprobe", mkvmerge="mkvmerge", capture=capture)


def test_dv_remux_verifier_requires_final_rpu_when_process_runner_is_available(monkeypatch, tmp_path):
    import dragontools.worker.dv_remux_output_verifier as module

    monkeypatch.setattr(
        module,
        "inspect_dynamic_hdr_with_mediainfo",
        lambda *_a, **_k: SimpleNamespace(conclusive=True, dolby_vision=True, dolby_vision_profile="8.1", warnings=()),
    )
    monkeypatch.setattr(module.OutputVerifier, "verify", lambda *_a, **_k: SimpleNamespace(ok=True, messages=[]))

    class Runner:
        def run_abortable_capture(self, cmd, *, timeout_s=None):
            if cmd[0] == "ffmpeg":
                Path(cmd[-1]).write_bytes(b"hevc")
                return 0, "", ""
            if cmd[0] == "dovi_tool":
                return 1, "", "no rpu"
            raise AssertionError(cmd)

    verifier = module.DVRemuxOutputVerifier(
        tools=SimpleNamespace(ffprobe="ffprobe", ffmpeg="ffmpeg", dovi_tool="dovi_tool"),
        process_runner=Runner(),
    )
    result = verifier.verify(output_path=str(tmp_path / "out.mkv"), container="mkv", expected_duration_ms=1000)
    assert result.ok is False
    assert any("RPU" in message for message in result.messages)


def test_dv_remux_verifier_accepts_nonempty_final_rpu(monkeypatch, tmp_path):
    import dragontools.worker.dv_remux_output_verifier as module

    monkeypatch.setattr(
        module,
        "inspect_dynamic_hdr_with_mediainfo",
        lambda *_a, **_k: SimpleNamespace(conclusive=True, dolby_vision=True, dolby_vision_profile="8.1", warnings=()),
    )
    monkeypatch.setattr(module.OutputVerifier, "verify", lambda *_a, **_k: SimpleNamespace(ok=True, messages=[]))

    class Runner:
        def run_abortable_capture(self, cmd, *, timeout_s=None):
            if cmd[0] == "ffmpeg":
                Path(cmd[-1]).write_bytes(b"hevc")
                return 0, "", ""
            if cmd[0] == "dovi_tool":
                out = Path(cmd[cmd.index("-o") + 1])
                out.write_bytes(b"rpu")
                return 0, "", ""
            raise AssertionError(cmd)

    verifier = module.DVRemuxOutputVerifier(
        tools=SimpleNamespace(ffprobe="ffprobe", ffmpeg="ffmpeg", dovi_tool="dovi_tool"),
        process_runner=Runner(),
    )
    result = verifier.verify(output_path=str(tmp_path / "out.mkv"), container="mkv", expected_duration_ms=1000)
    assert result.ok is True


def test_dv_output_commit_receives_abort_guard(monkeypatch, tmp_path):
    import dragontools.worker.dv_remux_output as module

    source = tmp_path / "movie.mkv"
    staging = tmp_path / "staging.mkv"
    source.write_bytes(b"source" * 300)
    staging.write_bytes(b"output" * 300)
    seen = {}

    def fake_commit(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(destination=kwargs["destination"], cleanup_pending=False, cleanup_message="", backup_path=None)

    monkeypatch.setattr(module, "commit_staged_output", fake_commit)
    worker = SimpleNamespace(
        overwrite_original=True, container="mkv", log=_noop, _log=_noop,
        abort_requested=False, abort_type=None,
    )
    manager = module.DVOutputManager(worker)
    result = manager._commit_overwrite(str(source), str(staging), source)
    assert result.destination == source
    assert callable(seen.get("abort_check"))
    worker.abort_requested = True
    worker.abort_type = "sofort"
    assert seen["abort_check"]() is True


def test_dv_file_override_lookup_is_path_canonical():
    from dragontools.worker.worker_contracts import file_override_for_path

    mapping = {r"C:\Media\Film.mkv": {"audio": {"mode": "selected"}}}
    assert file_override_for_path(mapping, "c:/media/film.mkv") == {"audio": {"mode": "selected"}}


def test_dv_policy_rejects_unknown_container():
    from dragontools.worker.dv_remux_policy import decide_dv_remux

    media = SimpleNamespace(has_dv=True, dv_profile_major=8, dv_profile="8", dolby_vision_profile="8")
    decision = decide_dv_remux(media, container="avi", keep_dv7_mkv=False, encode_dv5=True)
    assert decision.should_skip is True
    assert "Container" in decision.reason


def test_dv_muxer_rejects_unknown_container_without_running_tool():
    from dragontools.worker.dv_remux_muxers import DVRemuxMuxer

    calls = []
    worker = SimpleNamespace(container="avi", tools=SimpleNamespace(mp4box="MP4Box", mkvmerge="mkvmerge"), log=lambda *a: calls.append(a))
    runner = SimpleNamespace(run_abortable_capture=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("tool must not run")))
    muxer = DVRemuxMuxer(worker, runner)
    assert muxer.mux("video.hevc", [], "out.avi", []) is False
    assert any("Container" in str(item[0]) for item in calls)


def test_dv_final_output_service_rejects_unknown_container_without_mp4_fallback():
    from dragontools.worker.dv_final_output_service import DVFinalOutputService

    calls = []
    service = DVFinalOutputService(
        mp4box_muxer=SimpleNamespace(mux_final_output=lambda *_a, **_k: calls.append("mp4") or True),
        mkv_muxer=SimpleNamespace(mux_final_output=lambda *_a, **_k: calls.append("mkv") or True),
        log=lambda *a: calls.append(a), verbose_log=_noop,
        assert_nonempty_file=lambda *_a, **_k: True,
    )
    state = SimpleNamespace(
        request=SimpleNamespace(container="avi", output_path="out.avi"),
        files=SimpleNamespace(injected=Path("video.hevc")),
        mux_audio_tracks=[], mux_subtitle_tracks=[],
    )
    runner = SimpleNamespace(adapter=lambda **_k: _noop)
    assert service.mux(state, runner, verify_final_mux_metadata=lambda *_a, **_k: True) is False
    assert "mp4" not in calls and "mkv" not in calls


def test_media_analyzer_preserves_default_flags():
    from dragontools.core.media_analyzer_audio_streams import _build_audio_streams
    from dragontools.core.media_analyzer_subtitle_streams import _build_subtitle_streams

    audios = _build_audio_streams([], [{
        "index": 1, "codec_name": "aac", "channels": 2,
        "tags": {"language": "deu"}, "disposition": {"forced": 0, "default": 1},
    }])
    subs = _build_subtitle_streams([], [{
        "index": 2, "codec_name": "subrip",
        "tags": {"language": "deu"}, "disposition": {"forced": 1, "default": 1},
    }])
    assert audios[0].default is True
    assert subs[0].default is True


def test_output_contract_checks_default_flags():
    from dragontools.worker.media_contract_types import ExpectedAudioTrack, ExpectedMediaContract, ExpectedSubtitleTrack
    from dragontools.worker.output_contract_tracks import compare_audio_tracks, compare_subtitle_tracks

    contract = ExpectedMediaContract(
        container="mkv", video_codec="hevc", video_stream_count=1,
        audio_tracks=(ExpectedAudioTrack("eac3", 6, "de", default=True),),
        subtitle_tracks=(ExpectedSubtitleTrack("subrip", "de", True, default=False),),
    )
    audio_messages = compare_audio_tracks(contract, [{
        "codec_name": "eac3", "channels": 6, "tags": {"language": "deu"}, "disposition": {"default": 0}
    }])
    sub_messages = compare_subtitle_tracks(contract, [{
        "codec_name": "subrip", "tags": {"language": "deu"}, "disposition": {"forced": 1, "default": 1}
    }])
    assert any("Default-Flag" in msg for msg in audio_messages)
    assert any("Default-Flag" in msg for msg in sub_messages)


def test_direct_subtitle_args_preserve_default_flag():
    from dragontools.worker.dv_mkv_source_subtitles import direct_subtitle_args
    track = SimpleNamespace(language="de", title="Forced", forced=True, default=False, path=Path("source.mkv"))
    args = direct_subtitle_args(track, 9)
    assert ["--default-track-flag", "9:no"] == args[args.index("--default-track-flag"):args.index("--default-track-flag") + 2]


def test_mkv_muxer_writes_audio_default_flag(tmp_path):
    from dragontools.worker.dv_mkv_muxer import DVMKVMuxer
    from dragontools.worker.dv_audio_mux_service import DVMuxAudioTrack

    video = tmp_path / "video.hevc"
    audio = tmp_path / "audio.mka"
    output = tmp_path / "out.mkv"
    video.write_bytes(b"v")
    audio.write_bytes(b"a")
    seen = {}

    def run(cmd, **_kwargs):
        seen["cmd"] = list(cmd)
        output.write_bytes(b"out")
        return 0

    track = DVMuxAudioTrack(0, audio, {"lang": "de", "default": False})
    ok = DVMKVMuxer(mkvmerge_path="mkvmerge", audio_track_name=lambda _m: "").mux_final_output(
        run, output_path=str(output), injected_hevc=video, mux_tracks=[track], subtitle_tracks=[]
    )
    assert ok is True
    cmd = seen["cmd"]
    assert ["--default-track-flag", "0:no"] == cmd[cmd.index("--default-track-flag"):cmd.index("--default-track-flag") + 2]


def test_dv_remux_thread_isolates_nested_settings_and_rejects_invalid_container():
    """Source-level guard because the CI review image intentionally has no PyQt6."""
    source = (Path(__file__).parents[1] / "worker" / "dv_remux_thread.py").read_text(encoding="utf-8")
    assert "self.encoder_options = deepcopy(encoder_options or {})" in source
    assert "self.file_overrides = deepcopy(file_overrides or {})" in source
    assert "self.subtitle_rules = deepcopy(" in source
    assert "raise ValueError(f\"Ungültiger DV-Ausgabecontainer:" in source


def test_dv_remux_thread_update_override_replaces_path_alias_and_deepcopies_value():
    source = (Path(__file__).parents[1] / "worker" / "dv_remux_thread.py").read_text(encoding="utf-8")
    assert "if normalize_worker_path(existing_path) == path_n:" in source
    assert "self.file_overrides[path] = deepcopy(override or {})" in source


def test_verify_failure_preserves_remux_candidate_instead_of_cleanup(tmp_path):
    from dragontools.worker.dv_remux_job import DVRemuxJobRunner

    class Signal:
        def emit(self, *_args):
            pass

    source = tmp_path / "Film.mkv"
    staging = tmp_path / "__temp_dv_remux__" / "Film.mp4"
    source.write_bytes(b"source")
    preserve_calls = []
    cleanup_calls = []

    class Pipeline:
        last_expected_contract = None
        def run(self, **_kwargs):
            staging.parent.mkdir(parents=True, exist_ok=True)
            staging.write_bytes(b"candidate" * 256)
            return True

    class OutputManager:
        def build_output_path(self, _input):
            return str(staging)
        def verify_output(self, **_kwargs):
            return False
        def preserve_failed_output(self, input_path, output_path, *, reason):
            preserve_calls.append((input_path, output_path, reason))
            archived = tmp_path / "Archiv" / "failed.mp4"
            archived.parent.mkdir()
            Path(output_path).replace(archived)
            return str(archived)
        def cleanup_incomplete(self, *args):
            cleanup_calls.append(args)

    worker = SimpleNamespace(
        overwrite_original=True, container="mp4", subtitle_rules={},
        abort_requested=False, abort_type=None, tools=SimpleNamespace(),
        _postprocess_service=None, _sidecar_outputs={}, _postprocess_outputs={},
        _failure_details={}, worker_event=Signal(), file_result=Signal(),
        file_progress=Signal(), log=_noop,
    )
    job = DVRemuxJobRunner(
        worker, process_runner=SimpleNamespace(), pipeline=Pipeline(),
        output_manager=OutputManager(),
        subtitle_service=SimpleNamespace(),
        prepare_metadata=lambda _p: (
            source.name, SimpleNamespace(subtitle_streams=[], analysis_warnings=[]), 1000, None
        ),
    )
    assert job.run(str(source)) is False
    assert len(preserve_calls) == 1
    assert cleanup_calls == []
    assert source.exists()
    assert (tmp_path / "Archiv" / "failed.mp4").exists()


def test_output_manager_archives_only_known_failed_candidate(tmp_path):
    from dragontools.worker.dv_remux_output import DVOutputManager

    source = tmp_path / "Film.mkv"
    source.write_bytes(b"source")
    staging = tmp_path / "__temp_dv_remux__" / "Film.mp4"
    staging.parent.mkdir()
    staging.write_bytes(b"candidate" * 256)
    worker = SimpleNamespace(overwrite_original=True, container="mp4", log=_noop, _log=_noop)
    manager = DVOutputManager(worker)
    archived = manager.preserve_failed_output(str(source), str(staging), reason="RPU fehlt")
    assert archived is not None
    archived_path = Path(archived)
    assert archived_path.exists()
    assert archived_path.parent == tmp_path / "Archiv"
    assert not staging.exists()
    assert source.exists()
    status = archived_path.with_suffix(archived_path.suffix + ".recovery.json")
    assert status.exists()
    assert "RPU fehlt" in status.read_text(encoding="utf-8")


def test_direct_remux_mkv_muxer_preserves_audio_and_subtitle_default_flags(tmp_path):
    from dragontools.worker.dv_remux_muxers import DVRemuxMuxer
    from dragontools.worker.dv_subtitle_mux_service import DVMuxSubtitleTrack

    video = tmp_path / "video.hevc"
    audio = tmp_path / "audio.mka"
    subtitle = tmp_path / "sub.srt"
    output = tmp_path / "out.mkv"
    video.write_bytes(b"video")
    audio.write_bytes(b"audio")
    subtitle.write_text("dummy", encoding="utf-8")
    seen = {}

    class Runner:
        def run_abortable_capture(self, cmd, *, timeout_s=None):
            seen["cmd"] = list(cmd)
            output.write_bytes(b"output")
            return 0, "", ""

    worker = SimpleNamespace(
        container="mkv",
        tools=SimpleNamespace(mkvmerge="mkvmerge", ffprobe="ffprobe", mp4box="MP4Box"),
        abort_requested=False, abort_type=None, _last_stderr="", log=_noop,
    )
    track = DVMuxSubtitleTrack(
        path=subtitle, stream_index=2, codec="subrip", language="de", title="Deutsch",
        forced=False, default=True,
    )
    ok = DVRemuxMuxer(worker, Runner()).mux_mkv(
        str(video), [(str(audio), {"language": "de", "default": False})], str(output), [track]
    )
    assert ok is True
    flags = [
        seen["cmd"][i + 1]
        for i, value in enumerate(seen["cmd"][:-1])
        if value == "--default-track-flag"
    ]
    assert "0:no" in flags
    assert "0:yes" in flags


def test_direct_remux_expected_contract_carries_mkv_default_flags():
    from dragontools.worker.dv_remux_pipeline import DVRemuxPipelineRunner
    from dragontools.worker.dv_subtitle_mux_service import DVMuxSubtitleTrack

    worker = SimpleNamespace(
        container="mkv", subtitle_rules={}, log=_noop,
        tools=SimpleNamespace(ffmpeg="ffmpeg"),
    )
    pipeline = DVRemuxPipelineRunner(
        worker, SimpleNamespace(),
        audio_plan_builder=lambda **_k: [], audio_title_builder=lambda **_k: "",
        audio_filter_builder=lambda _d: None,
    )
    media = SimpleNamespace(
        primary_video=SimpleNamespace(codec="hevc", bit_depth=10, width=1920, height=1080),
        audio_streams=[SimpleNamespace(index=1, channels=2, default=True)],
    )
    contract = pipeline._build_expected_contract(
        media,
        [{"stream_index": 1, "codec": "aac", "channels": 2, "language": "de", "default": True}],
        [DVMuxSubtitleTrack(Path("sub.srt"), 2, "subrip", "de", "", True, default=False)],
        expected_dv_profile=8,
    )
    assert contract.audio_tracks[0].default is True
    assert contract.subtitle_tracks[0].default is False


def test_output_manager_refuses_to_archive_unrelated_file(tmp_path):
    from dragontools.worker.dv_remux_output import DVOutputManager

    source = tmp_path / "Film.mkv"
    unrelated = tmp_path / "do_not_touch.mp4"
    source.write_bytes(b"source")
    unrelated.write_bytes(b"important" * 256)
    worker = SimpleNamespace(overwrite_original=True, container="mp4", log=_noop, _log=_noop)
    manager = DVOutputManager(worker)
    assert manager.preserve_failed_output(str(source), str(unrelated), reason="test") is None
    assert unrelated.exists()
    assert not (tmp_path / "Archiv").exists()
