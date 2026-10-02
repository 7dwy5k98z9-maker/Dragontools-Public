# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import threading
from pathlib import Path
from types import SimpleNamespace

from dragontools.core.models import MediaInfo, VideoStream
from dragontools.worker.converter_process_executor import ConverterProcessExecutor
from dragontools.worker.dv_encode_command import build_dv_encode_command
from dragontools.worker.dv_runtime_models import DVEncoderConfig
from dragontools.worker.encode_plan_service import EncodePlanService
from dragontools.worker.encoder_args import _vid_args, encoder_10bit_filter_pixel_format
from dragontools.worker.hdr10_color import hdr10_setparams_filter


class _Logger:
    def info(self, _message):
        pass


class _StreamArgs:
    def __init__(self):
        self.pre_filters: list[str] = []
        self.post_filters: list[str] = []

    def sub_args(self, *_args):
        return [], ["-sn"]

    def build_vf_args(self, _input, _output, _mi, _burn, pre_filters, post_filters=None):
        self.pre_filters = list(pre_filters)
        self.post_filters = list(post_filters or [])
        filters = self.pre_filters + self.post_filters
        return ["-map", "0:v:0"] + (["-vf", ",".join(filters)] if filters else [])

    def audio_args(self, *_args):
        return ["-an"]

    def audio_input_args(self, *_args):
        return []


def _hdr_media() -> MediaInfo:
    video = VideoStream(
        index=0,
        codec="hevc",
        width=3840,
        height=2160,
        hdr_format="hdr10",
        pix_fmt="yuv420p10le",
        bit_depth=10,
        color_space="bt2020nc",
        color_transfer="smpte2084",
        color_primaries="bt2020",
    )
    return MediaInfo(
        path="in.mkv",
        video_streams=[video],
        audio_streams=[],
        subtitle_streams=[],
        is_hdr=True,
        transfer_characteristics="smpte2084",
        matrix_coefficients="bt2020nc",
    )


def _plan(encoder: str):
    streams = _StreamArgs()
    service = EncodePlanService(
        codec="h265",
        encoder_options={"encoder": encoder},
        scale_mode="none",
        detect_imax_auto=lambda *_: False,
        detect_crop=lambda *_: None,
        probe_duration_ms=lambda *_: 0,
        stream_args_helper=streams,
        log=lambda *_: None,
        logger=_Logger(),
    )
    service.prepare_encode_plan("in.mkv", "out.mkv", _hdr_media(), "standard", "mkv", {})
    return streams


def test_cpu_and_hardware_filter_pixel_formats_are_encoder_native():
    assert encoder_10bit_filter_pixel_format("cpu") == "yuv420p10le"
    assert encoder_10bit_filter_pixel_format({"encoder": "cpu"}) == "yuv420p10le"
    assert encoder_10bit_filter_pixel_format("nvenc") == "p010le"
    assert encoder_10bit_filter_pixel_format("qsv") == "p010le"
    assert encoder_10bit_filter_pixel_format("amf") == "p010le"


def test_standard_hdr10_cpu_filter_does_not_force_p010():
    streams = _plan("cpu")
    assert streams.post_filters == [hdr10_setparams_filter("cpu")]
    assert "format=yuv420p10le" in streams.post_filters[0]
    assert "p010le" not in streams.post_filters[0]


def test_standard_hdr10_nvenc_filter_keeps_p010():
    streams = _plan("nvenc")
    assert streams.post_filters == [hdr10_setparams_filter("nvenc")]
    assert "format=p010le" in streams.post_filters[0]


def test_dv_cpu_filter_chain_stays_planar_10bit(tmp_path: Path):
    built = build_dv_encode_command(
        ffmpeg_path="ffmpeg",
        encoder_config=DVEncoderConfig(
            codec="h265",
            crf=22,
            preset="medium",
            options={"encoder": "cpu", "bf": 8, "rc_lookahead": 40},
        ),
        input_path="source.mkv",
        p8_hevc=tmp_path / "p8.hevc",
        output_hevc=tmp_path / "encoded.hevc",
        vf_args=["-map", "0:v:0", "-vf", "crop=3840:1632:0:264,subtitles='forced.srt'"],
        profile_major=7,
    )
    chain = built.command[built.command.index("-vf") + 1]
    assert "format=yuv420p10le" in chain
    assert "format=p010le" not in chain
    assert built.command[built.command.index("-pix_fmt") + 1] == "yuv420p10le"


def test_dv_nvenc_filter_chain_keeps_p010(tmp_path: Path):
    built = build_dv_encode_command(
        ffmpeg_path="ffmpeg",
        encoder_config=DVEncoderConfig(
            codec="h265",
            crf=22,
            preset="p6",
            options={"encoder": "nvenc", "preset": "p6", "cq": 22, "bf": 4, "rc_lookahead": 40},
        ),
        input_path="source.mkv",
        p8_hevc=tmp_path / "p8.hevc",
        output_hevc=tmp_path / "encoded.hevc",
        vf_args=["-map", "0:v:0", "-vf", "crop=3840:1632:0:264"],
        profile_major=7,
    )
    chain = built.command[built.command.index("-vf") + 1]
    assert "format=p010le" in chain
    assert built.command[built.command.index("-pix_fmt") + 1] == "p010le"


def test_cpu_compression_tuning_bframes_and_lookahead_remain_unchanged():
    args = _vid_args(
        "h265",
        22,
        "medium",
        {
            "encoder": "cpu",
            "aq_mode": "2",
            "aq_strength": "1.0",
            "psy_rd": "2.0",
            "psy_rdoq": "1.0",
            "bf": 8,
            "rc_lookahead": 40,
        },
    )
    params = args[args.index("-x265-params") + 1]
    assert "bframes=8" in params
    assert "rc-lookahead=40" in params


class _VerboseCollector:
    def __init__(self):
        self.lines: list[str] = []

    def write(self, text: str) -> None:
        self.lines.append(str(text))


class _Worker:
    def __init__(self):
        self._lock = threading.Lock()
        self._current_process = None
        self._paused = False
        self.abort_requested = False
        self.abort_type = None
        self._verbose_logger = _VerboseCollector()
        self._last_stderr = ""

    def log(self, _message: str, _level: str = "info") -> None:
        pass


def test_progress_executor_copies_x265_thread_diagnostics_to_verbose_log(tmp_path: Path):
    worker = _Worker()
    executor = ConverterProcessExecutor(worker)
    code = (
        "import sys; "
        "print('x265 [info]: Thread pool created using 16 threads', file=sys.stderr); "
        "print('x265 [info]: frame threads / pool features       : 4 / wpp(26 rows)', file=sys.stderr); "
        "print('x265 [info]: Coding QT: not needed in verbose log', file=sys.stderr); "
        "print('frame=1'); print('progress=end')"
    )

    def read_progress(proc, _path, _dur_ms, _total_frames, note_activity):
        assert proc.stdout is not None
        for _line in proc.stdout:
            note_activity()

    rc = executor.run_progress(
        [sys.executable, "-c", code],
        str(tmp_path / "input.mkv"),
        1000,
        timeout_s=5,
        label="x265-Diagnose",
        probe_frames=lambda *_: None,
        read_progress=read_progress,
    )

    assert rc == 0
    joined = "\n".join(worker._verbose_logger.lines)
    assert "Thread pool created using 16 threads" in joined
    assert "frame threads / pool features" in joined
    assert "Coding QT" not in joined
