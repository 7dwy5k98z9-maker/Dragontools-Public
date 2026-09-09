from types import SimpleNamespace

import importlib.util

import pytest

from dragontools.core.settings import (
    SET_KEY_NFO_ENABLED,
    SET_KEY_TRICKPLAY_ENABLED,
)
from dragontools.worker.workflow_services import WorkflowConfig, WorkflowServices
from dragontools.worker.workflow_pipeline_executor import WorkflowPipelineExecutor
from dragontools.worker.workflow_models import PipelineExecutionRequest, PipelineExecutionResult


HAS_PYQT6 = importlib.util.find_spec("PyQt6") is not None


class _FakeSettings:
    def __init__(self, values=None):
        self._values = dict(values or {})

    def value(self, key, default=None, type=None):
        value = self._values.get(key, default)
        if type is bool:
            return bool(value)
        return value


def _queue_owner(*, overrides=None, preflight_rows=None, settings=None):
    from dragontools.gui.convert_widget_queue_actions import ConvertWidgetQueueActionsMixin

    owner = ConvertWidgetQueueActionsMixin()
    owner._state = SimpleNamespace(
        file_overrides=dict(overrides or {}),
        preflight_rows_by_path=dict(preflight_rows or {}),
    )
    owner.settings = settings or _FakeSettings()
    return owner


def test_workflow_effective_strip_only_uses_per_file_override():
    svc = WorkflowServices.__new__(WorkflowServices)
    svc._config = WorkflowConfig(
        codec="h265",
        crf=23,
        preset="medium",
        scale_mode="original",
        encoder_options={},
        strip_only=False,
    )

    assert svc._effective_strip_only({"processing_mode": "strip_only"}) is True
    assert svc._effective_strip_only({"processing_mode": "auto"}) is False


def test_workflow_pipeline_executor_uses_strip_runner_for_per_file_strip_only():
    calls = []

    class _Pipeline:
        def execute(self, _request):
            raise AssertionError("Strip-only darf keine Encode-Pipeline aufrufen")

    temp_state = SimpleNamespace(
        reset_diagnostics=lambda: None,
        failure_reason="",
        failure_stage="",
        stderr="",
        last_tool="",
        last_command="",
    )
    executor = WorkflowPipelineExecutor(
        standard_pipeline=_Pipeline(),
        strip_runner=lambda *args: calls.append(args) or True,
        dv_pipeline=_Pipeline(),
        hdrplus_pipeline=_Pipeline(),
        temp_state=temp_state,
    )
    analysis = SimpleNamespace()
    request = PipelineExecutionRequest(
        pipeline="standard",
        input_path="in.mkv",
        output_path="out.mkv",
        container="mkv",
        media_info=analysis,
        plan=None,
        override={"processing_mode": "strip_only"},
        strip_only=True,
        duration_ms=None,
        codec="h265",
        crf=23,
        preset="medium",
        encoder_options={},
    )

    result = executor.execute(request)

    assert result == PipelineExecutionResult.succeeded()
    assert calls == [("in.mkv", "out.mkv", analysis, {"processing_mode": "strip_only"}, "mkv")]


@pytest.mark.skipif(not HAS_PYQT6, reason="PyQt6 wird fuer den GUI-Queue-Mixin benoetigt")
def test_queue_label_shows_processing_badge_from_override():
    path = r"C:\in\film.mkv"
    owner = _queue_owner(overrides={path: {"processing_mode": "strip_only"}})

    assert owner._override_label_text(path).endswith("[Verarbeitung: Strip-Only]")


@pytest.mark.skipif(not HAS_PYQT6, reason="PyQt6 wird fuer den GUI-Queue-Mixin benoetigt")
def test_queue_label_shows_pipeline_and_postprocess_badges_from_cache():
    path = r"C:\in\film.mkv"
    owner = _queue_owner(
        preflight_rows={path: {"preview": {"pipeline": "dv"}}},
        settings=_FakeSettings({
            SET_KEY_NFO_ENABLED: True,
            SET_KEY_TRICKPLAY_ENABLED: False,
        }),
    )

    label = owner._override_label_text(path)

    assert "[Encode: DV, Postprocessing: NFO]" in label


@pytest.mark.skipif(not HAS_PYQT6, reason="PyQt6 wird fuer den GUI-Queue-Mixin benoetigt")
def test_queue_label_shows_dv_hdr10plus_and_named_postprocess_badges():
    path = r"C:\in\film.mkv"
    owner = _queue_owner(
        preflight_rows={
            path: {
                "preview": {
                    "pipeline": "dv",
                    "video": {"has_dv": True, "has_hdr10plus": True},
                    "effective_preserve_dv": True,
                    "effective_preserve_hdrplus": True,
                }
            }
        },
        settings=_FakeSettings({
            SET_KEY_NFO_ENABLED: True,
            SET_KEY_TRICKPLAY_ENABLED: True,
        }),
    )

    label = owner._override_label_text(path)

    assert "[Encode: DV + HDR10+, Postprocessing: NFO + Trickplay]" in label
