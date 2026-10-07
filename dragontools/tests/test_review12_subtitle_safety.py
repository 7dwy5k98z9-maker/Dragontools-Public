from __future__ import annotations

from dragontools.tests.subtitle_command_fixtures import subtitle_command_validation

from pathlib import Path
from types import SimpleNamespace

import pytest

from dragontools.core.models import MediaInfo, SubtitleStream
from dragontools.rules.subtitle_plan_models import MP4SubtitleStoragePlan, SubtitlePlan
from dragontools.rules.subtitle_plan_service import compute_subtitle_plan_service


def _sub(
    index: int,
    *,
    language: str = "de",
    codec: str = "subrip",
    title: str = "Deutsch",
    forced: bool = False,
    default: bool = False,
) -> SubtitleStream:
    return SubtitleStream(
        index=index,
        language=language,
        forced=forced,
        title=title,
        codec=codec,
        default=default,
    )


def _identity(stream: SubtitleStream) -> dict:
    return {
        "language": stream.language,
        "codec": stream.codec,
        "title": stream.title,
        "forced": stream.forced,
        "default": stream.default,
    }


def test_custom_subtitle_override_remaps_by_source_identity_after_reorder():
    wanted = _sub(5, forced=True, title="Deutsch Forced")
    stale_slot = _sub(2, language="en", title="English")
    override = {
        "subtitle_mode": "custom",
        "subtitle_tracks": [
            {
                "index": 2,
                "keep": False,
                "burn_in": True,
                "source_identity": _identity(wanted),
            }
        ],
    }

    plan = compute_subtitle_plan_service(
        [stale_slot, wanted],
        file_override=override,
        subtitle_rules={},
    )

    assert plan.burn_sub is wanted
    assert plan.keep_streams == ()


def test_custom_subtitle_override_with_ambiguous_identity_fails_closed_not_auto():
    stale_slot = _sub(2, language="en", title="English")
    candidate_a = _sub(5, forced=True, title="Deutsch Forced")
    candidate_b = _sub(6, forced=True, title="Deutsch Forced")
    override = {
        "subtitle_mode": "custom",
        "subtitle_tracks": [
            {
                "index": 2,
                "keep": False,
                "burn_in": True,
                "source_identity": _identity(candidate_a),
            }
        ],
    }

    plan = compute_subtitle_plan_service(
        [stale_slot, candidate_a, candidate_b],
        file_override=override,
        subtitle_rules={},
    )

    assert plan.burn_sub is None
    assert plan.keep_streams == ()
    assert plan.external_streams == ()


def test_mp4_subtitle_args_use_iso639_2_and_preserve_default_plus_forced():
    from dragontools.worker.converter_subtitle_args import _mp4_args

    stream = _sub(4, language="de", forced=True, default=True)
    plan = SubtitlePlan("custom", None, (stream,), (stream,))
    worker = SimpleNamespace(_logger=SimpleNamespace(decision=lambda *_: None))

    _burn, args = _mp4_args(
        worker,
        plan,
        None,
        {"mp4_sidecars_enabled": False},
    )

    assert "language=deu" in args
    pos = args.index("-disposition:s:0")
    assert args[pos + 1] == "default+forced"


def test_media_contract_contains_subtitle_default_flag():
    from dragontools.worker.media_contract_builder import _build_subtitle_tracks

    stream = _sub(4, default=True)
    media = MediaInfo(path="film.mkv", audio_streams=[], subtitle_streams=[stream], video_streams=[])
    plan = SubtitlePlan("custom", None, (stream,), (stream,))

    tracks = _build_subtitle_tracks(
        media,
        {"subtitle_mode": "custom"},
        "mkv",
        False,
        {},
        subtitle_planner=lambda *_args, **_kwargs: plan,
        mp4_storage_planner=lambda *_args, **_kwargs: MP4SubtitleStoragePlan((stream,), ()),
        subtitle_codec_family=lambda codec: str(codec),
    )

    assert len(tracks) == 1
    assert tracks[0].default is True


def test_bitmap_ocr_abort_only_honors_immediate_abort():
    from dragontools.worker.bitmap_subtitle_ocr_service import BitmapSubtitleOcrService

    service = object.__new__(BitmapSubtitleOcrService)
    service.worker = SimpleNamespace(abort_requested=True, abort_type="nach_datei")
    assert service._abort_requested() is False

    service.worker.abort_type = "sofort"
    assert service._abort_requested() is True


def test_media_language_abort_only_honors_immediate_abort():
    from dragontools.worker.media_stream_language_service import MediaStreamLanguageService

    service = object.__new__(MediaStreamLanguageService)
    service.worker = SimpleNamespace(abort_requested=True, abort_type="nach_datei")
    assert service._abort_requested() is False

    service.worker.abort_type = "sofort"
    assert service._abort_requested() is True


def test_sidecar_failure_removes_partial_staging_file(monkeypatch, tmp_path):
    import dragontools.worker.subtitle_sidecar_service as module
    from dragontools.worker.subtitle_sidecar_targets import SidecarTarget

    stream = _sub(3)
    target_path = tmp_path / "Film.de.srt"
    target = SidecarTarget(
        stream=stream,
        language="de",
        key=("de", False),
        number=None,
        output_path=str(target_path),
        codec_args=("-c:s", "copy"),
        output_codec="subrip",
    )
    service = module.SubtitleSidecarService(
        ffmpeg_path="ffmpeg",
        subtitle_rules={},
        log=lambda *_: None,
    )

    def fake_run(cmd, **_kwargs):
        Path(cmd[-1]).write_text("partial", encoding="utf-8")
        return SimpleNamespace(returncode=1, stdout="", stderr="broken", aborted=False, timed_out=False)

    monkeypatch.setattr(module, "run_tool", fake_run)
    ok, failure, aborted = service._export_target("input.mkv", target)

    assert ok is False
    assert failure is not None
    assert aborted is False
    assert not target_path.exists()
    assert not list(tmp_path.glob("*.dragontools-*"))


def test_pgs_ocr_failure_keeps_successfully_exported_original(monkeypatch, tmp_path):
    import dragontools.worker.subtitle_sidecar_service as module

    pgs = _sub(3, codec="hdmv_pgs_subtitle", forced=True)
    media = MediaInfo(path="input.mkv", audio_streams=[], subtitle_streams=[pgs], video_streams=[])
    worker = SimpleNamespace(
        settings=SimpleNamespace(value=lambda _key, default=None, **_kwargs: default),
        tools=SimpleNamespace(ffmpeg="ffmpeg", ffprobe="ffprobe", tesseract="tesseract"),
        abort_requested=False,
        abort_type=None,
    )
    service = module.SubtitleSidecarService(
        ffmpeg_path="ffmpeg",
        subtitle_rules={"pgs_to_srt_enabled": True},
        log=lambda *_: None,
        worker=worker,
    )
    selection = SimpleNamespace(
        normal_streams=(pgs,),
        ass_srt_streams=(),
        pgs_srt_streams=(pgs,),
        storage=SimpleNamespace(internal_streams=(), external_streams=(pgs,)),
        plan=SimpleNamespace(burn_warnings=()),
    )

    monkeypatch.setattr(module, "select_sidecar_streams", lambda *_args, **_kwargs: selection)

    def fake_run(cmd, **_kwargs):
        Path(cmd[-1]).write_bytes(b"PGS")
        return SimpleNamespace(returncode=0, stdout="", stderr="", aborted=False, timed_out=False)

    monkeypatch.setattr(module, "run_tool", fake_run)
    monkeypatch.setattr(
        module.BitmapSubtitleOcrService,
        "create_srt",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("Tesseract failed")),
    )

    result = service.export_sidecars_result(
        input_path="input.mkv",
        output_base=tmp_path / "Film",
        media_info=media,
        container="mp4",
    )

    assert result.complete is True
    assert result.aborted is False
    assert len(result.exported_paths) == 1
    original = Path(result.exported_paths[0])
    assert original.exists()
    assert original.suffix == ".sup"
    assert not (tmp_path / "Film.de.forced.srt").exists()


def test_pgs_ocr_immediate_abort_is_propagated(monkeypatch, tmp_path):
    import dragontools.worker.subtitle_sidecar_service as module

    pgs = _sub(3, codec="hdmv_pgs_subtitle")
    media = MediaInfo(path="input.mkv", audio_streams=[], subtitle_streams=[pgs], video_streams=[])
    state = SimpleNamespace(abort_requested=False, abort_type=None)
    worker = SimpleNamespace(
        settings=SimpleNamespace(value=lambda _key, default=None, **_kwargs: default),
        tools=SimpleNamespace(ffmpeg="ffmpeg", ffprobe="ffprobe", tesseract="tesseract"),
        _control_state=state,
    )
    service = module.SubtitleSidecarService(
        ffmpeg_path="ffmpeg",
        subtitle_rules={"pgs_to_srt_enabled": True},
        log=lambda *_: None,
        worker=worker,
    )
    selection = SimpleNamespace(
        normal_streams=(),
        ass_srt_streams=(),
        pgs_srt_streams=(pgs,),
        storage=SimpleNamespace(internal_streams=(pgs,), external_streams=()),
        plan=SimpleNamespace(burn_warnings=()),
    )
    monkeypatch.setattr(module, "select_sidecar_streams", lambda *_args, **_kwargs: selection)

    def aborting_ocr(*_args, **_kwargs):
        state.abort_requested = True
        state.abort_type = "sofort"
        raise RuntimeError("OCR wurde abgebrochen")

    monkeypatch.setattr(module.BitmapSubtitleOcrService, "create_srt", aborting_ocr)

    result = service.export_sidecars_result(
        input_path="input.mkv",
        output_base=tmp_path / "Film",
        media_info=media,
        container="mkv",
    )

    assert result.aborted is True
    assert result.exported_paths == ()


def test_mkvmerge_warning_output_is_committed(monkeypatch, tmp_path):
    import dragontools.subtitle.injector as module

    output = tmp_path / "Film_sub.mkv"

    def fake_run(cmd, **_kwargs):
        stage = Path(cmd[cmd.index("-o") + 1])
        stage.write_bytes(b"muxed")
        return SimpleNamespace(returncode=1, ok=False, stdout="", stderr="warning")

    monkeypatch.setattr(module, "run_tool", fake_run)

    assert module.inject_with_mkvmerge(
        "Film.mkv",
        "Film.de.srt",
        str(output),
        language="de",
    ) is True
    assert output.read_bytes() == b"muxed"
    assert not list(tmp_path.glob("*.dragontools-*"))


def test_ffmpeg_injection_failure_does_not_poison_retry_target(monkeypatch, tmp_path):
    import dragontools.subtitle.injector as module

    output = tmp_path / "Film_sub.mp4"

    def failing_run(cmd, **_kwargs):
        Path(cmd[-1]).write_bytes(b"partial")
        return SimpleNamespace(returncode=1, ok=False, stdout="", stderr="broken")

    monkeypatch.setattr(module, "run_tool", failing_run)
    assert module.inject_with_ffmpeg(
        "Film.mp4",
        "Film.de.srt",
        str(output),
        map_existing_subtitles=False,
        subtitle_codec="mov_text",
    ) is False
    assert not output.exists()
    assert not list(tmp_path.glob("*.dragontools-*"))

    def succeeding_run(cmd, **_kwargs):
        Path(cmd[-1]).write_bytes(b"valid")
        return SimpleNamespace(returncode=0, ok=True, stdout="", stderr="")

    monkeypatch.setattr(module, "run_tool", succeeding_run)
    assert module.inject_with_ffmpeg(
        "Film.mp4",
        "Film.de.srt",
        str(output),
        map_existing_subtitles=False,
        subtitle_codec="mov_text",
    ) is True
    assert output.read_bytes() == b"valid"


def test_mp4_injection_preserves_existing_subtitles_and_converts_only_new_track(monkeypatch, tmp_path):
    import dragontools.subtitle.injector as module

    output = tmp_path / "Film_sub.mp4"
    calls: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        calls.append(list(cmd))
        if "-select_streams" in cmd:
            return SimpleNamespace(
                returncode=0,
                ok=True,
                stdout='{"streams":[{"index":2},{"index":3}]}',
                stderr="",
            )
        Path(cmd[-1]).write_bytes(b"valid")
        return SimpleNamespace(returncode=0, ok=True, stdout="", stderr="")

    monkeypatch.setattr(module, "run_tool", fake_run)
    assert module.inject_with_ffmpeg(
        "Film.mp4",
        "Film.de.srt",
        str(output),
        ffprobe="ffprobe",
        subtitle_codec="mov_text",
        map_existing_subtitles=True,
        language="de",
    ) is True

    ffmpeg_cmd = calls[-1]
    assert ffmpeg_cmd[ffmpeg_cmd.index("-map") + 1] == "0"
    second_map = ffmpeg_cmd.index("-map", ffmpeg_cmd.index("-map") + 1)
    assert ffmpeg_cmd[second_map + 1] == "1:s:0"
    assert "-c:s" not in ffmpeg_cmd
    assert "-c:s:2" in ffmpeg_cmd
    assert ffmpeg_cmd[ffmpeg_cmd.index("-c:s:2") + 1] == "mov_text"
    assert "language=deu" in ffmpeg_cmd


def test_extractor_failure_removes_partial_staging(monkeypatch, tmp_path):
    import dragontools.subtitle.extractor as module

    output = tmp_path / "Film.de.srt"

    def fake_run(cmd, **_kwargs):
        Path(cmd[-1]).write_text("partial", encoding="utf-8")
        return SimpleNamespace(returncode=1, ok=False, stdout="", stderr="broken")

    monkeypatch.setattr(module, "run_tool", fake_run)
    assert module.extract_with_ffmpeg("Film.mkv", 3, str(output)) is False
    assert not output.exists()
    assert not list(tmp_path.glob("*.dragontools-*"))


def test_bitmap_burn_overlays_before_crop_and_scale():
    from dragontools.worker.converter_video_filter_args import image_burn_vf_args

    burn = _sub(3, codec="hdmv_pgs_subtitle")
    media = SimpleNamespace(subtitle_streams=[burn])
    args = image_burn_vf_args(
        media,
        burn,
        ["crop=1920:800:0:140", "scale=1280:-2"],
        ["format=yuv420p10le"],
    )
    graph = args[args.index("-filter_complex") + 1]

    assert graph.startswith("[0:v:0][0:s:0]overlay[vburn];")
    assert graph.index("overlay") < graph.index("crop=") < graph.index("scale=")
    assert args.count("-map") == 1
    assert args[-1] == "[vout]"


def test_ass_burn_preserves_ass_format_and_source_canvas_order(monkeypatch, tmp_path):
    import dragontools.worker.converter_stream_args as module

    logs: list[tuple[str, str]] = []
    worker = SimpleNamespace(
        tools=SimpleNamespace(ffmpeg="ffmpeg"),
        log=lambda message, level="info": logs.append((message, level)),
        _burn_sub_tmp=None,
    )
    helper = module.ConverterStreamArgsHelper(worker)
    burn = _sub(3, codec="ass")
    seen: dict[str, list[str]] = {}

    def fake_run(cmd, **_kwargs):
        seen["cmd"] = list(cmd)
        Path(cmd[-1]).write_text("[Script Info]\n[Events]\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, aborted=False, timed_out=False, stdout="", stderr="")

    monkeypatch.setattr(module, "run_tool", fake_run)
    args = helper.text_burn_vf_args(
        "Film.mkv",
        str(tmp_path / "out.mkv"),
        burn,
        ["crop=1920:800:0:140", "scale=1280:-2"],
        ["format=yuv420p10le"],
    )

    cmd = seen["cmd"]
    assert cmd[cmd.index("-c:s") + 1] == "ass"
    assert Path(cmd[-1]).suffix == ".ass"
    vf = args[args.index("-vf") + 1]
    assert vf.index("subtitles=") < vf.index("crop=") < vf.index("scale=")
    Path(cmd[-1]).unlink(missing_ok=True)


@pytest.mark.parametrize("default, expect_disable", [(True, False), (False, True)])
def test_dv_remux_mp4_preserves_subtitle_default_as_track_enable_flag(tmp_path, default, expect_disable):
    from dragontools.worker.dv_remux_muxers import DVRemuxMuxer
    from dragontools.worker.dv_subtitle_mux_service import DVMuxSubtitleTrack

    video = tmp_path / "video.hevc"
    subtitle = tmp_path / "Deutsch.srt"
    output = tmp_path / "Film.mp4"
    video.write_bytes(b"video")
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nHallo\n", encoding="utf-8")
    seen: dict[str, list[str]] = {}

    class Runner:
        def run_abortable_capture(self, cmd, **_kwargs):
            seen["cmd"] = list(cmd)
            output.write_bytes(b"mp4")
            return 0, "", ""

    worker = SimpleNamespace(
        tools=SimpleNamespace(mp4box="MP4Box"),
        abort_requested=False,
        abort_type=None,
        _last_stderr="",
        log=lambda *_: None,
    )
    track = DVMuxSubtitleTrack(
        path=subtitle,
        stream_index=4,
        codec="subrip",
        language="deu",
        title="Deutsch",
        forced=False,
        default=default,
    )

    assert DVRemuxMuxer(worker, Runner()).mux_mp4(str(video), [], str(output), [track]) is True
    add_arg = next(arg for arg in seen["cmd"] if str(subtitle) in str(arg))
    assert (":disable" in add_arg) is expect_disable


@pytest.mark.parametrize("default, expect_disable", [(True, False), (False, True)])
def test_dv_mp4box_muxer_preserves_subtitle_default_as_track_enable_flag(tmp_path, default, expect_disable):
    from dragontools.worker.dv_mp4box_muxer import DVMP4BoxMuxer

    subtitle = tmp_path / "Deutsch.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nHallo\n", encoding="utf-8")
    track = SimpleNamespace(
        path=subtitle,
        language="deu",
        title="Deutsch",
        forced=True,
        default=default,
    )
    commands: list[list[str]] = []
    muxer = DVMP4BoxMuxer(mp4box_path="MP4Box", audio_track_name=lambda _meta: "")

    assert muxer.mux_final_output(
        lambda cmd: commands.append(list(cmd)) or 0,
        output_path=str(tmp_path / "Film.mp4"),
        injected_hevc="video.hevc",
        mux_tracks=[],
        subtitle_tracks=[track],
    ) is True
    add_arg = next(arg for arg in commands[0] if str(subtitle) in str(arg))
    assert ":hdlr=text:txtflags=0xC0000000" in add_arg
    assert (":disable" in add_arg) is expect_disable


@pytest.mark.parametrize("default, expect_disable", [(True, False), (False, True)])
def test_hdrplus_mp4_preserves_forced_and_default_subtitle_flags(tmp_path, default, expect_disable):
    from dragontools.worker.hdrplus_mux_service import HDRPlusMuxService

    video = tmp_path / "video.hevc"
    subtitle = tmp_path / "Deutsch.srt"
    output = tmp_path / "Film.mp4"
    video.write_bytes(b"video")
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nHallo\n", encoding="utf-8")
    seen: dict[str, list[str]] = {}

    def run_mux_tool(cmd, **_kwargs):
        seen["cmd"] = list(cmd)
        output.write_bytes(b"x" * 2048)
        return True

    service = HDRPlusMuxService(
        tools=SimpleNamespace(mp4box="MP4Box", ffmpeg="ffmpeg", ffprobe="ffprobe"),
        log=lambda *_: None,
        run_mux_tool=run_mux_tool,
        capture_tool=lambda *_args, **_kwargs: SimpleNamespace(ok=True, stdout='{"streams": []}'),
    )
    track = SimpleNamespace(
        path=subtitle,
        language="deu",
        title="Deutsch Forced",
        forced=True,
        default=default,
    )

    assert service.mux_mp4(
        str(video),
        "",
        str(output),
        tmp_dir=tmp_path,
        subtitle_tracks=[track],
    ) is True
    add_arg = next(arg for arg in seen["cmd"] if str(subtitle) in str(arg))
    assert ":hdlr=text:txtflags=0xC0000000" in add_arg
    assert (":disable" in add_arg) is expect_disable


def test_custom_subtitle_override_empty_list_means_select_nothing_not_auto():
    forced = _sub(2, forced=True, title="Deutsch Forced")
    regular = _sub(3, title="Deutsch")

    plan = compute_subtitle_plan_service(
        [forced, regular],
        file_override={"subtitle_mode": "custom", "subtitle_tracks": []},
        subtitle_rules={},
    )

    assert plan.burn_sub is None
    assert plan.keep_streams == ()
    assert plan.external_streams == ()


def test_pgs_ocr_collision_never_deletes_existing_user_srt(monkeypatch, tmp_path):
    import dragontools.worker.subtitle_sidecar_service as module

    pgs = _sub(3, codec="hdmv_pgs_subtitle", forced=True)
    media = MediaInfo(path="input.mkv", audio_streams=[], subtitle_streams=[pgs], video_streams=[])
    worker = SimpleNamespace(
        settings=SimpleNamespace(value=lambda _key, default=None, **_kwargs: default),
        tools=SimpleNamespace(ffmpeg="ffmpeg", ffprobe="ffprobe", tesseract="tesseract"),
        abort_requested=False,
        abort_type=None,
    )
    service = module.SubtitleSidecarService(
        ffmpeg_path="ffmpeg",
        subtitle_rules={"pgs_to_srt_enabled": True},
        log=lambda *_: None,
        worker=worker,
    )
    selection = SimpleNamespace(
        normal_streams=(), ass_srt_streams=(), pgs_srt_streams=(pgs,),
        storage=SimpleNamespace(internal_streams=(pgs,), external_streams=()),
        plan=SimpleNamespace(burn_warnings=()),
    )
    monkeypatch.setattr(module, "select_sidecar_streams", lambda *_args, **_kwargs: selection)
    target = tmp_path / "Film.de.forced.srt"
    target.write_text("MANUELLER UNTERTITEL", encoding="utf-8")
    monkeypatch.setattr(
        module.BitmapSubtitleOcrService,
        "create_srt",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileExistsError("exists")),
    )

    result = service.export_sidecars_result(
        input_path="input.mkv", output_base=tmp_path / "Film", media_info=media, container="mkv"
    )

    assert result.aborted is False
    assert target.read_text(encoding="utf-8") == "MANUELLER UNTERTITEL"


def test_ocr_exclusive_writer_never_overwrites_existing_target(tmp_path):
    from dragontools.worker.bitmap_subtitle_ocr_service import _write_srt_exclusive

    target = tmp_path / "Film.de.srt"
    target.write_text("USER", encoding="utf-8")
    with pytest.raises(FileExistsError):
        _write_srt_exclusive(target, "OCR")
    assert target.read_text(encoding="utf-8") == "USER"


def test_external_sidecar_filename_preserves_default_flag():
    from dragontools.worker.subtitle_sidecar_targets import build_sidecar_targets
    from dragontools.worker.subtitle_sidecar_service import sidecar_filename
    from dragontools.core.lang_codes import sub_codec_to_ext_and_args

    stream = _sub(4, language="de", default=True, forced=True)
    targets, unsupported = build_sidecar_targets(
        [stream],
        Path("/media/Film"),
        language_tag=lambda _lang: "de",
        filename_builder=sidecar_filename,
        codec_resolver=sub_codec_to_ext_and_args,
    )

    assert unsupported == []
    assert len(targets) == 1
    assert Path(targets[0].output_path).name == "Film.de.default.forced.srt"
