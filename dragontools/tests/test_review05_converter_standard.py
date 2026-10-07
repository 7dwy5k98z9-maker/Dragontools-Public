from __future__ import annotations

from types import SimpleNamespace

import pytest


def _request(*, pipeline: str = "standard"):
    from dragontools.worker.workflow_models import PipelineExecutionRequest

    return PipelineExecutionRequest(
        pipeline=pipeline,
        input_path="in.mkv",
        output_path="out.mkv",
        container="mkv",
        media_info=SimpleNamespace(),
        plan=SimpleNamespace(vf_args=["-map", "0:v:0"], audio_args=[], audio_input_args=[], sn=[]),
        override={},
        strip_only=False,
        duration_ms=1000,
        codec="h265",
        crf=23,
        preset="medium",
        encoder_options={"encoder": "cpu"},
    )


def test_unknown_pipeline_fails_closed_instead_of_running_standard():
    from dragontools.worker.workflow_models import PipelineExecutionResult
    from dragontools.worker.workflow_pipeline_executor import WorkflowPipelineExecutor

    class Pipeline:
        def __init__(self):
            self.calls = []

        def execute(self, request):
            self.calls.append(request)
            return PipelineExecutionResult.succeeded()

    standard = Pipeline()
    temp = SimpleNamespace(
        reset_diagnostics=lambda: None,
        failure_reason="",
        failure_stage="",
        stderr="",
        last_tool="",
        last_command="",
    )
    executor = WorkflowPipelineExecutor(
        standard_pipeline=standard,
        strip_runner=lambda *_args: True,
        dv_pipeline=Pipeline(),
        hdrplus_pipeline=Pipeline(),
        temp_state=temp,
    )

    result = executor.execute(_request(pipeline="typo_pipeline"))

    assert result.success is False
    assert result.failure_stage == "Pipeline-Auswahl"
    assert "typo_pipeline" in result.failure_reason
    assert standard.calls == []


def test_image_burn_rejects_stale_subtitle_stream_instead_of_burning_first_track():
    from dragontools.worker.converter_video_filter_args import image_burn_vf_args

    mi = SimpleNamespace(
        subtitle_streams=[
            SimpleNamespace(index=4, codec="hdmv_pgs_subtitle"),
            SimpleNamespace(index=7, codec="hdmv_pgs_subtitle"),
        ]
    )
    stale_burn = SimpleNamespace(index=99, codec="hdmv_pgs_subtitle")

    with pytest.raises(ValueError, match="99"):
        image_burn_vf_args(mi, stale_burn, [], [])


def test_converter_file_executor_resolves_override_by_canonical_path():
    from dragontools.worker.converter_file_executor import ConverterFileExecutor

    calls = []
    worker = SimpleNamespace(
        _services=SimpleNamespace(
            workflow_runner=SimpleNamespace(run=lambda path, override: calls.append((path, override)) or True),
            source_visual_check=None,
        ),
        _job_state=SimpleNamespace(
            file_overrides={r"C:\Media\Film.mkv": {"processing_mode": "strip_only"}},
            overwrite_original=False,
            strip_only=False,
        ),
        _session_state=SimpleNamespace(keep_verbose_log=False, failure_details={}),
        emit_file_result=lambda *_args: None,
        emit_file_progress=lambda *_args: None,
    )
    executor = ConverterFileExecutor(worker)
    executor._check_source_visual_quality = lambda *_args: True

    assert executor.execute(r"c:/media/FILM.mkv") is True
    assert calls
    assert calls[0][1].get("processing_mode") == "strip_only"


def test_crop_detection_ignores_crop_lines_from_failed_ffmpeg(monkeypatch):
    from dragontools.worker import converter_detection
    from dragontools.worker.converter_detection import ConverterDetectionHelper

    monkeypatch.setattr(
        converter_detection.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="[Parsed_cropdetect_0] crop=1800:800:60:140\nDecoder failed\n",
        ),
    )
    worker = SimpleNamespace(
        tools=SimpleNamespace(ffmpeg="ffmpeg"),
        log=lambda *_args: None,
        _logger=SimpleNamespace(info=lambda *_args: None),
    )

    assert ConverterDetectionHelper(worker).detect_crop("film.mkv", 1920, 1080) is None


def test_imax_detection_ignores_failed_ffmpeg_probes(monkeypatch):
    from dragontools.worker import converter_detection
    from dragontools.worker.converter_detection import ConverterDetectionHelper

    def fake_run(cmd, **_kwargs):
        offset = int(cmd[cmd.index("-ss") + 1])
        crop = "crop=1920:1080:0:0" if offset < 200 else "crop=1920:804:0:138"
        return SimpleNamespace(returncode=1, stdout="", stderr=crop)

    monkeypatch.setattr(converter_detection.subprocess, "run", fake_run)
    worker = SimpleNamespace(
        tools=SimpleNamespace(ffmpeg="ffmpeg"),
        log=lambda *_args: None,
        _logger=SimpleNamespace(info=lambda *_args: None),
    )

    assert ConverterDetectionHelper(worker).detect_imax_auto(
        "film.mkv", duration_s=400, source_w=1920, source_h=1080, interval_s=90
    ) is False


def test_encoder_persistence_can_restore_combo_by_item_data():
    from dragontools.gui import encoder_settings_persistence as module

    class Combo:
        def __init__(self):
            self.items = [("Auto/Default", "auto"), ("fullres", "fullres")]
            self.index = 1

        def findData(self, value):
            return next((i for i, (_text, data) in enumerate(self.items) if data == value), -1)

        def findText(self, value):
            return next((i for i, (text, _data) in enumerate(self.items) if text == value), -1)

        def setCurrentIndex(self, index):
            self.index = index

        def setCurrentText(self, value):
            idx = self.findText(value)
            if idx >= 0:
                self.index = idx

    combo = Combo()
    helper = getattr(module, "_apply_combo_value", lambda *_args: False)

    assert helper(combo, "auto") is True
    assert combo.index == 0


def test_encoder_quality_ranges_match_codec_and_backend_limits():
    from dragontools.gui import encoder_settings_options as module

    quality_range = getattr(module, "encoder_quality_range", lambda *_args: (0, 63))

    assert quality_range("h265", "cpu") == (0, 51)
    assert quality_range("h265", "nvenc") == (0, 51)
    assert quality_range("av1", "nvenc") == (0, 63)
    assert quality_range("h265", "qsv") == (1, 51)


def test_cpu_h265_crf_is_clamped_to_valid_x265_range():
    from dragontools.worker.encoder_args import _vid_args

    args = _vid_args("h265", 63, "medium", {"encoder": "cpu"})

    assert args[args.index("-crf") + 1] == "51"


def test_av1_nvenc_honors_selected_b_ref_mode():
    from dragontools.worker.encoder_args import _vid_args

    args = _vid_args(
        "av1",
        28,
        "medium",
        {
            "encoder": "nvenc",
            "cq": 28,
            "bf": 4,
            "bref_mode": "middle",
            "rc_lookahead": 32,
        },
    )

    assert args[args.index("-b_ref_mode") + 1] == "middle"


def test_probe_frames_rejects_stdout_from_failed_ffprobe(monkeypatch):
    from dragontools.worker import converter_media_probe

    monkeypatch.setattr(
        converter_media_probe.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=2, stdout="12345\n", stderr="probe failed"),
    )
    worker = SimpleNamespace(
        tools=SimpleNamespace(ffprobe="ffprobe"),
        log=lambda *_args: None,
    )

    assert converter_media_probe.probe_frames(worker, "broken.mkv") is None


def test_queue_is_current_uses_canonical_path_comparison():
    from dragontools.worker.converter_queue_state import ConverterQueueState

    queue = ConverterQueueState([r"C:\Media\Film.mkv"])
    queue.next_file(0)

    assert queue.is_current(r"c:/media/FILM.mkv") is True
