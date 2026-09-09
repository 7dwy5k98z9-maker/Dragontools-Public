# -*- coding: utf-8 -*-
from types import SimpleNamespace

from dragontools.core.models import MediaInfo, VideoStream
from dragontools.worker.dv_encode_command import dv_video_encode_args
from dragontools.worker.dv_runtime_models import DVEncoderConfig
from dragontools.worker.encode_plan_service import EncodePlanService
from dragontools.worker.hdr10_color import DV_P5_LIBPLACEBO_FILTER, HDR10_SETPARAMS_FILTER
from dragontools.worker.standard_pipeline_runner import StandardPipelineRunner
from dragontools.worker.workflow_models import PipelineExecutionRequest


class _Logger:
    def __init__(self):
        self.lines = []

    def info(self, message):
        self.lines.append(str(message))


class _StreamArgs:
    def __init__(self):
        self.pre_filters = None
        self.post_filters = None

    def sub_args(self, *_):
        return [], ["-sn"]

    def build_vf_args(self, _input_path, _output_path, _mi, _burn, pre_filters, post_filters=None):
        self.pre_filters = list(pre_filters)
        self.post_filters = list(post_filters or [])
        filters = self.pre_filters + self.post_filters
        return ["-map", "0:v:0"] + (["-vf", ",".join(filters)] if filters else [])

    def audio_args(self, *_):
        return ["-an"]

    def audio_input_args(self, *_):
        return []


def _standard_request(ctx, *, encoder_options):
    return PipelineExecutionRequest(
        pipeline="standard",
        input_path=ctx.input_path,
        output_path=ctx.output_path,
        container=ctx.container,
        media_info=ctx.analysis,
        plan=ctx.plan,
        override={},
        strip_only=False,
        duration_ms=ctx.duration_ms,
        codec="h265",
        crf=23,
        preset="medium",
        encoder_options=dict(encoder_options),
    )


def _media_info(*, hdr_format="dolby_vision", dv_profile=7):
    is_hdr = hdr_format in {"dolby_vision", "hdr10", "hdr10plus"}
    video = VideoStream(
        index=0,
        codec="hevc",
        width=3840,
        height=2160,
        hdr_format=hdr_format,
        pix_fmt="yuv420p10le" if is_hdr else "yuv420p",
        bit_depth=10 if is_hdr else 8,
        color_space="bt2020nc" if is_hdr else "bt709",
        color_transfer="smpte2084" if is_hdr else "bt709",
        color_primaries="bt2020" if is_hdr else "bt709",
    )
    return MediaInfo(
        path="in.mkv",
        audio_streams=[],
        subtitle_streams=[],
        video_streams=[video],
        is_hdr=is_hdr,
        has_hdr10plus=hdr_format == "hdr10plus",
        dolby_vision_profile=str(dv_profile) if hdr_format == "dolby_vision" else None,
        dolby_vision=hdr_format == "dolby_vision",
        dv_profile=str(dv_profile) if hdr_format == "dolby_vision" else None,
        dv_profile_major=dv_profile if hdr_format == "dolby_vision" else None,
        transfer_characteristics="smpte2084" if is_hdr else "bt709",
        matrix_coefficients="bt2020nc" if is_hdr else "bt709",
    )


def _plan_service(stream_args):
    return EncodePlanService(
        codec="h265",
        encoder_options={},
        scale_mode="none",
        detect_imax_auto=lambda *_: False,
        detect_crop=lambda *_: None,
        probe_duration_ms=lambda *_: 0,
        stream_args_helper=stream_args,
        log=lambda *_: None,
        logger=_Logger(),
    )


def test_dv7_standard_encode_keeps_hdr10_base_color_tags():
    stream_args = _StreamArgs()
    service = _plan_service(stream_args)

    plan = service.prepare_encode_plan(
        "in.mkv",
        "out.mkv",
        _media_info(dv_profile=7),
        "standard",
        "mkv",
        {},
    )

    assert stream_args.pre_filters == []
    assert stream_args.post_filters == [HDR10_SETPARAMS_FILTER]
    assert "zscale=matrixin=ictcp" not in " ".join(plan.vf_args)
    assert "color_trc=smpte2084" in " ".join(plan.vf_args)


def test_dv7_string_profile_keeps_hdr10_base_color_tags():
    stream_args = _StreamArgs()
    service = _plan_service(stream_args)
    media_info = _media_info(dv_profile=7)
    media_info.dv_profile_major = "7"

    service.prepare_encode_plan(
        "in.mkv",
        "out.mkv",
        media_info,
        "standard",
        "mkv",
        {},
    )

    assert stream_args.post_filters == [HDR10_SETPARAMS_FILTER]


def test_dv5_standard_encode_uses_libplacebo_conversion_then_hdr10_tags():
    stream_args = _StreamArgs()
    service = _plan_service(stream_args)

    plan = service.prepare_encode_plan(
        "in.mkv",
        "out.mkv",
        _media_info(dv_profile=5),
        "standard",
        "mkv",
        {},
    )

    assert stream_args.pre_filters == [DV_P5_LIBPLACEBO_FILTER]
    assert stream_args.post_filters == [HDR10_SETPARAMS_FILTER]
    assert "libplacebo=" in " ".join(plan.vf_args)
    assert "zscale=matrixin=ictcp" not in " ".join(plan.vf_args)
    assert "color_trc=smpte2084" in " ".join(plan.vf_args)


def test_dv_cpu_encode_args_use_x265_placebo_and_cpu_10bit_format():
    args = dv_video_encode_args(
        DVEncoderConfig(
            codec="h265",
            crf=21,
            preset="placebo",
            options={"encoder": "cpu", "aq_mode": 2, "bf": 8, "rc_lookahead": 40},
        )
    )

    assert args[args.index("-c:v") + 1] == "libx265"
    assert args[args.index("-preset") + 1] == "placebo"
    assert args.count("-pix_fmt") == 1
    assert args[args.index("-pix_fmt") + 1] == "yuv420p10le"
    assert args[args.index("-color_primaries") + 1] == "bt2020"
    assert args[args.index("-color_trc") + 1] == "smpte2084"
    assert args[args.index("-colorspace") + 1] == "bt2020nc"


def test_standard_runner_sets_hdr10_output_flags_for_dv7_h265():
    commands = []

    runner = StandardPipelineRunner(
        tools=SimpleNamespace(ffmpeg="ffmpeg"),
        codec="h265",
        crf=23,
        preset="medium",
        encoder_options={"encoder": "cpu"},
        progress_runner=lambda cmd, *_: commands.append(cmd) or 0,
        log=lambda *_: None,
    )
    ctx = SimpleNamespace(
        input_path="in.mkv",
        output_path="out.mkv",
        container="mkv",
        duration_ms=1000,
        analysis=_media_info(dv_profile=7),
        plan=SimpleNamespace(
            vf_args=["-map", "0:v:0", "-vf", HDR10_SETPARAMS_FILTER],
            audio_args=["-an"],
            sn=["-sn"],
        ),
    )

    assert runner.execute(_standard_request(ctx, encoder_options={"encoder": "cpu"})).success is True
    cmd = commands[0]
    assert cmd[cmd.index("-pix_fmt") + 1] == "yuv420p10le"
    assert cmd.count("-pix_fmt") == 1
    assert cmd[cmd.index("-color_primaries") + 1] == "bt2020"
    assert cmd[cmd.index("-color_trc") + 1] == "smpte2084"
    assert cmd[cmd.index("-colorspace") + 1] == "bt2020nc"
    x265_params = cmd[cmd.index("-x265-params") + 1]
    assert "colorprim=bt2020" in x265_params
    assert "transfer=smpte2084" in x265_params
    assert "colormatrix=bt2020nc" in x265_params
    assert "range=limited" in x265_params
    assert "hdr10=1" in x265_params


def test_standard_runner_leaves_sdr_output_untagged():
    commands = []
    sdr = _media_info(hdr_format=None, dv_profile=None)

    runner = StandardPipelineRunner(
        tools=SimpleNamespace(ffmpeg="ffmpeg"),
        codec="h265",
        crf=23,
        preset="medium",
        encoder_options={"encoder": "cpu"},
        progress_runner=lambda cmd, *_: commands.append(cmd) or 0,
        log=lambda *_: None,
    )
    ctx = SimpleNamespace(
        input_path="in.mkv",
        output_path="out.mkv",
        container="mkv",
        duration_ms=1000,
        analysis=sdr,
        plan=SimpleNamespace(vf_args=["-map", "0:v:0"], audio_args=["-an"], sn=["-sn"]),
    )

    assert runner.execute(_standard_request(ctx, encoder_options={"encoder": "cpu"})).success is True
    assert "-color_trc" not in commands[0]


def test_standard_runner_entfernt_veraltete_video_statistik_tags():
    commands = []
    sdr = _media_info(hdr_format=None, dv_profile=None)

    runner = StandardPipelineRunner(
        tools=SimpleNamespace(ffmpeg="ffmpeg"),
        codec="h265",
        crf=23,
        preset="medium",
        encoder_options={"encoder": "nvenc"},
        progress_runner=lambda cmd, *_: commands.append(cmd) or 0,
        log=lambda *_: None,
    )
    ctx = SimpleNamespace(
        input_path="in.mkv",
        output_path="out.mkv",
        container="mkv",
        duration_ms=1000,
        analysis=sdr,
        plan=SimpleNamespace(vf_args=["-map", "0:v:0"], audio_args=["-an"], sn=["-sn"]),
    )

    assert runner.execute(_standard_request(ctx, encoder_options={"encoder": "nvenc"})).success is True
    cmd = commands[0]
    for tag in ("BPS", "DURATION", "NUMBER_OF_FRAMES", "NUMBER_OF_BYTES"):
        assert "-metadata:s:v:0" in cmd
        assert f"{tag}=" in cmd


def test_standard_runner_preserves_ffmpeg_failure_diagnostics():
    worker = SimpleNamespace(_last_stderr="encoder failed\ninvalid argument")
    runner = StandardPipelineRunner(
        tools=SimpleNamespace(ffmpeg=r"C:\\Tools\\ffmpeg.exe"),
        codec="h265",
        crf=23,
        preset="medium",
        encoder_options={"encoder": "cpu"},
        progress_runner=lambda *_: 17,
        log=lambda *_: None,
        worker=worker,
    )
    ctx = SimpleNamespace(
        input_path="input file.mkv",
        output_path="output file.mkv",
        container="mkv",
        duration_ms=1000,
        analysis=_media_info(hdr_format=None, dv_profile=None),
        plan=SimpleNamespace(vf_args=["-map", "0:v:0"], audio_args=["-an"], sn=["-sn"]),
    )

    result = runner.execute(_standard_request(ctx, encoder_options={"encoder": "cpu"}))

    assert result.success is False
    assert result.failure_stage == "Standard-Encoding"
    assert result.failure_reason == "ffmpeg wurde mit Returncode 17 beendet."
    assert result.tool == "ffmpeg.exe"
    assert '"input file.mkv"' in result.command
    assert result.tool_output == "encoder failed\ninvalid argument"


def test_encode_plan_treats_string_false_imax_and_autocrop_flags_as_false():
    stream_args = _StreamArgs()
    calls = {"imax": 0, "crop": 0}

    def detect_imax(*_):
        calls["imax"] += 1
        return True

    def detect_crop(*_):
        calls["crop"] += 1
        return "crop=1:1:0:0"

    service = EncodePlanService(
        codec="h265",
        encoder_options={
            "imax_auto_detect": "false",
            "autocrop_enabled": "false",
            "imax_probe_interval_s": "90.0",
        },
        scale_mode="none",
        detect_imax_auto=detect_imax,
        detect_crop=detect_crop,
        probe_duration_ms=lambda *_: 0,
        stream_args_helper=stream_args,
        log=lambda *_: None,
        logger=_Logger(),
    )

    plan = service.prepare_encode_plan(
        "in.mkv", "out.mkv", _media_info(hdr_format="hdr10"),
        "standard", "mkv", {"imax": "false"},
    )

    assert calls == {"imax": 0, "crop": 0}
    assert plan.crop is None
