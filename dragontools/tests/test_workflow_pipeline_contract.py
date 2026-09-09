# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from dragontools.core.models import Pipeline
from dragontools.worker.dv_runtime_models import DVTempState
from dragontools.worker.workflow_models import (
    PipelineExecutionRequest,
    PipelineExecutionResult,
)
from dragontools.worker.workflow_pipeline_executor import WorkflowPipelineExecutor


class _Pipeline:
    def __init__(self, result: PipelineExecutionResult):
        self.result = result
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
        return self.result


class _TempState(DVTempState):
    def __init__(self):
        super().__init__()
        self.reset_count = 0

    def reset_diagnostics(self) -> None:
        self.reset_count += 1
        super().reset_diagnostics()


def _request(*, pipeline="standard", strip_only=False, preserve_hdrplus=False):
    return PipelineExecutionRequest(
        pipeline=pipeline,
        input_path="in.mkv",
        output_path="out.mkv",
        container="mkv",
        media_info=SimpleNamespace(),
        plan=SimpleNamespace(
            vf_args=[],
            audio_args=[],
            audio_input_args=[],
            sn=[],
            burn_sub_or_vf=False,
            crop=None,
        ),
        override={"test": True},
        strip_only=strip_only,
        duration_ms=1000,
        codec="h265",
        crf=23,
        preset="p6",
        encoder_options={"encoder": "nvenc"},
        preserve_hdrplus=preserve_hdrplus,
    )


def test_pipeline_request_from_context_normalisiert_enum_und_kopiert_mutable_daten():
    override = {"audio_tracks": [{"index": 1}]}
    encoder_options = {"encoder": "nvenc"}
    ctx = SimpleNamespace(
        pipeline=Pipeline.DV,
        input_path="in.mkv",
        output_path="out.mp4",
        container="mp4",
        analysis=SimpleNamespace(),
        plan=SimpleNamespace(),
        strip_only=False,
        duration_ms=1200,
        effective_codec="h265",
        effective_crf=21,
        effective_preset="p7",
        effective_encoder_options=encoder_options,
        effective_preserve_hdrplus=True,
    )

    request = PipelineExecutionRequest.from_context(ctx, override)
    override["later"] = True
    encoder_options["preset"] = "changed"

    assert request.pipeline == "dv"
    assert request.preserve_hdrplus is True
    assert request.override == {"audio_tracks": [{"index": 1}]}
    assert request.encoder_options == {"encoder": "nvenc"}


def test_pipeline_executor_dispatches_dv_via_typed_executor():
    temp_state = _TempState()
    dv = _Pipeline(PipelineExecutionResult.succeeded(sidecar_paths=["out.de.srt"]))
    executor = WorkflowPipelineExecutor(
        standard_pipeline=_Pipeline(PipelineExecutionResult.succeeded()),
        strip_runner=lambda *_: False,
        dv_pipeline=dv,
        hdrplus_pipeline=_Pipeline(PipelineExecutionResult.succeeded()),
        temp_state=temp_state,
    )

    result = executor.execute(_request(pipeline="dv", preserve_hdrplus=True))

    assert result.success is True
    assert result.sidecar_paths == ("out.de.srt",)
    assert len(dv.requests) == 1
    assert dv.requests[0].preserve_hdrplus is True
    assert temp_state.reset_count == 1


def test_pipeline_executor_strip_only_bypasses_dv_hdrplus_and_standard():
    temp_state = _TempState()
    calls = []
    standard = _Pipeline(PipelineExecutionResult.succeeded())
    dv = _Pipeline(PipelineExecutionResult.succeeded())
    hdr = _Pipeline(PipelineExecutionResult.succeeded())
    executor = WorkflowPipelineExecutor(
        standard_pipeline=standard,
        strip_runner=lambda *args: calls.append(args) or True,
        dv_pipeline=dv,
        hdrplus_pipeline=hdr,
        temp_state=temp_state,
    )

    result = executor.execute(_request(pipeline="dv", strip_only=True))

    assert result.success is True
    assert len(calls) == 1
    assert not standard.requests
    assert not dv.requests
    assert not hdr.requests


def test_pipeline_executor_preserves_structured_strip_failure_diagnostics():
    temp_state = _TempState()
    temp_state.record_failure(
        reason="ffmpeg rc=9",
        stage="Strip-Mux",
        tool="ffmpeg",
        command="ffmpeg -i in.mkv",
        output="stderr-tail",
    )

    # reset_diagnostics() loescht Altzustand. Der Runner setzt den aktuellen
    # Fehler deshalb innerhalb desselben Calls neu.
    def fail_strip(*_args):
        temp_state.record_failure(
            reason="ffmpeg rc=9",
            stage="Strip-Mux",
            tool="ffmpeg",
            command="ffmpeg -i in.mkv",
            output="stderr-tail",
        )
        return False

    executor = WorkflowPipelineExecutor(
        standard_pipeline=_Pipeline(PipelineExecutionResult.succeeded()),
        strip_runner=fail_strip,
        dv_pipeline=_Pipeline(PipelineExecutionResult.succeeded()),
        hdrplus_pipeline=_Pipeline(PipelineExecutionResult.succeeded()),
        temp_state=temp_state,
    )

    result = executor.execute(_request(strip_only=True))

    assert result.success is False
    assert result.failure_reason == "ffmpeg rc=9"
    assert result.failure_stage == "Strip-Mux"
    assert result.tool == "ffmpeg"
    assert result.command == "ffmpeg -i in.mkv"
    assert result.tool_output == "stderr-tail"


def test_workflow_services_maps_structured_pipeline_failure_without_runner_introspection():
    from dragontools.worker.workflow_services import WorkflowServices
    from dragontools.worker.workflow_models import WorkflowConfig

    failure = PipelineExecutionResult(
        success=False,
        sidecar_paths=("partial.de.srt",),
        failure_reason="RPU konnte nicht injiziert werden",
        failure_stage="DV-RPU",
        tool_output="dovi_tool failed",
        tool="dovi_tool",
        command="dovi_tool inject-rpu ...",
    )

    class Executor:
        def execute(self, _request):
            return failure

    logs = []
    svc = WorkflowServices.__new__(WorkflowServices)
    svc._config = WorkflowConfig(
        codec="h265",
        crf=23,
        preset="p6",
        scale_mode="original",
        encoder_options={},
        strip_only=False,
    )
    svc._pipeline_executor = Executor()
    svc._temp_state = DVTempState()
    svc._logger = SimpleNamespace(
        info=lambda msg: logs.append(("info", msg)),
        error=lambda msg: logs.append(("error", msg)),
    )
    ctx = SimpleNamespace(
        pipeline="dv",
        input_path="in.mkv",
        output_path="out.mp4",
        container="mp4",
        analysis=SimpleNamespace(has_dv=True),
        plan=SimpleNamespace(),
        strip_only=False,
        duration_ms=1000,
        effective_codec="h265",
        effective_crf=23,
        effective_preset="p6",
        effective_encoder_options={},
        effective_preserve_hdrplus=False,
    )

    with pytest.raises(RuntimeError, match="DV-RPU"):
        svc.process(ctx, {})

    assert ctx.sidecar_paths == ["partial.de.srt"]
    assert ctx.pipeline_failure_reason == "RPU konnte nicht injiziert werden"
    assert ctx.pipeline_failure_tool == "dovi_tool"
    assert ctx.pipeline_failure_command == "dovi_tool inject-rpu ..."
    assert any("dovi_tool failed" in msg for _level, msg in logs)


def test_workflow_refactor_has_explicit_boundaries_and_no_private_pipeline_peeking():
    worker_dir = Path(__file__).resolve().parents[1] / "worker"
    workflow_source = (worker_dir / "workflow_services.py").read_text(encoding="utf-8")
    factory_source = (worker_dir / "workflow_factory.py").read_text(encoding="utf-8")

    assert len(workflow_source.splitlines()) < 220
    assert "__self__" not in workflow_source
    assert "._encoder_config" not in workflow_source
    assert "._hdrplus_helper" not in workflow_source
    assert "getattr(self._pipeline_executor" not in workflow_source
    assert "WorkflowPlanningService(" in factory_source
    assert "WorkflowPipelineExecutor(" in factory_source
    assert "WorkflowVerificationService(" in factory_source
    assert "WorkflowOutputCommitCoordinator(" in factory_source


def test_workflow_refactor_components_stay_bounded():
    worker_dir = Path(__file__).resolve().parents[1] / "worker"
    limits = {
        "workflow_services.py": 220,
        "workflow_models.py": 130,
        "workflow_pipeline_executor.py": 100,
        "dv_workflow_pipeline_adapter.py": 90,
        "workflow_planning_service.py": 220,
        "workflow_verification_service.py": 150,
        "workflow_output_commit.py": 300,
        "workflow_factory.py": 100,
    }
    for filename, limit in limits.items():
        lines = (worker_dir / filename).read_text(encoding="utf-8").splitlines()
        assert len(lines) < limit, f"{filename}: {len(lines)} >= {limit}"


def test_pipeline_request_from_context_preserves_string_enum_value_for_h265():
    from dragontools.core.models import TargetCodec

    ctx = SimpleNamespace(
        pipeline=Pipeline.DV,
        input_path="in.mkv",
        output_path="out.mp4",
        container="mp4",
        analysis=SimpleNamespace(),
        plan=SimpleNamespace(),
        strip_only=False,
        duration_ms=1200,
        effective_codec=TargetCodec.H265,
        effective_crf=21,
        effective_preset="p7",
        effective_encoder_options={"encoder": "nvenc"},
        effective_preserve_hdrplus=False,
    )

    request = PipelineExecutionRequest.from_context(ctx, {})

    assert request.codec == "h265"
