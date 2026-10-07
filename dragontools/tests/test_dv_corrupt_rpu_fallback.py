from __future__ import annotations

from types import SimpleNamespace

import pytest

from dragontools.worker.dv_runtime_models import DVTempState
from dragontools.worker.workflow_models import PipelineExecutionResult, WorkflowConfig
from dragontools.worker.workflow_services import WorkflowServices


class _Logger:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def info(self, message: str) -> None:
        self.messages.append(("info", message))

    def warn(self, message: str) -> None:
        self.messages.append(("warn", message))

    def error(self, message: str) -> None:
        self.messages.append(("error", message))


class _Planning:
    def __init__(self) -> None:
        self.overrides: list[dict] = []
        self.refresh_calls: list[dict] = []

    def build_plan(self, ctx, override: dict) -> None:
        self.overrides.append(dict(override))
        # Model the real replanning priority: after DV is disabled, existing
        # HDR10+ remains eligible and wins over the standard pipeline.
        preserve_hdrplus = bool(
            override.get("preserve_hdrplus", getattr(ctx, "effective_preserve_hdrplus", False))
        )
        if bool(getattr(ctx.analysis, "has_hdrplus", False)) and preserve_hdrplus:
            ctx.pipeline = "hdrplus"
        else:
            ctx.pipeline = "standard"
        ctx.container = "mkv"
        ctx.output_path = "out.mkv"
        ctx.plan = SimpleNamespace(crop=None)
        ctx.effective_preserve_dv = False

    def refresh_media_contract(self, _ctx, override: dict, **kwargs) -> None:
        self.refresh_calls.append({"override": dict(override), **kwargs})


class _Executor:
    def __init__(self, results) -> None:
        self._results = list(results)
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
        return self._results.pop(0)


def _ctx(*, has_hdrplus: bool = False, preserve_hdrplus: bool = False):
    return SimpleNamespace(
        pipeline="dv",
        input_path="in.mkv",
        output_path="out.mp4",
        container="mp4",
        analysis=SimpleNamespace(has_dv=True, has_hdrplus=has_hdrplus),
        plan=SimpleNamespace(crop=None),
        strip_only=False,
        duration_ms=60_000,
        effective_codec="h265",
        effective_crf=22,
        effective_preset="medium",
        effective_encoder_options={
            "preserve_dv": True,
            "preserve_hdrplus": preserve_hdrplus,
        },
        effective_preserve_dv=True,
        effective_preserve_hdrplus=preserve_hdrplus,
        generate_hdr10plus=False,
    )


def _services(first_result, second_result=None):
    temp_state = DVTempState()
    logger = _Logger()
    planning = _Planning()
    results = [first_result]
    if second_result is not None:
        results.append(second_result)
    executor = _Executor(results)

    svc = WorkflowServices.__new__(WorkflowServices)
    svc._config = WorkflowConfig(
        codec="h265",
        crf=22,
        preset="medium",
        scale_mode="original",
        encoder_options={"preserve_dv": True},
        strip_only=False,
    )
    svc._temp_state = temp_state
    svc._logger = logger
    svc._planning = planning
    svc._pipeline_executor = executor
    return svc, temp_state, logger, planning, executor


def test_invalid_rpu_last_byte_falls_back_once_to_non_dv_encode():
    failure = PipelineExecutionResult(
        success=False,
        failure_stage="STEP 3/7 RPU-Extraktion",
        failure_reason="STEP 3/7 RPU-Extraktion: dovi_tool.exe fehlgeschlagen (rc=1)",
        tool_output="Error: Invalid RPU last byte: 248",
        tool="dovi_tool.exe",
        command='dovi_tool.exe -m 2 extract-rpu -i "in.mkv" -o metadata.rpu',
    )
    success = PipelineExecutionResult.succeeded()
    svc, temp_state, logger, planning, executor = _services(failure, success)
    ctx = _ctx()
    original_override = {
        "encoder_profile": {
            "codec": "h265",
            "encoder_options": {"preserve_dv": True},
        }
    }

    svc.process(ctx, original_override)

    assert [request.pipeline for request in executor.requests] == ["dv", "standard"]
    assert executor.requests[1].override["preserve_dv"] is False
    assert planning.overrides == [{
        **original_override,
        "preserve_dv": False,
    }]
    assert ctx.strategy_name == "standard"
    assert ctx.pipeline == "standard"
    assert ctx.output_path == "out.mkv"
    assert temp_state.failure_reason == ""
    warnings = [message for level, message in logger.messages if level == "warn"]
    assert len(warnings) == 1
    assert "Invalid RPU last byte: 248" in warnings[0]
    assert "Dolby Vision wird für diese Datei deaktiviert" in warnings[0]
    assert "HDR10+-Policy bleibt unverändert" in warnings[0]


def test_invalid_rpu_last_byte_keeps_detected_hdr10plus_enabled():
    failure = PipelineExecutionResult(
        success=False,
        failure_stage="STEP 3/7 RPU-Extraktion",
        failure_reason="STEP 3/7 RPU-Extraktion: dovi_tool.exe fehlgeschlagen (rc=1)",
        tool_output="Error: Invalid RPU last byte: 248",
        tool="dovi_tool.exe",
        command='dovi_tool.exe -m 2 extract-rpu -i "in.mkv" -o metadata.rpu',
    )
    success = PipelineExecutionResult.succeeded(verified_hdr10plus=True)
    svc, _temp_state, logger, planning, executor = _services(failure, success)
    ctx = _ctx(has_hdrplus=True, preserve_hdrplus=True)
    original_override = {
        "preserve_hdrplus": True,
        "encoder_profile": {
            "codec": "h265",
            "encoder_options": {
                "preserve_dv": True,
                "preserve_hdrplus": True,
            },
        },
    }

    svc.process(ctx, original_override)

    assert [request.pipeline for request in executor.requests] == ["dv", "hdrplus"]
    assert planning.overrides == [{
        **original_override,
        "preserve_dv": False,
    }]
    assert executor.requests[1].override["preserve_dv"] is False
    assert executor.requests[1].override["preserve_hdrplus"] is True
    assert "generate_hdr10plus" not in executor.requests[1].override
    assert ctx.strategy_name == "hdrplus"
    assert ctx.pipeline == "hdrplus"
    assert ctx.pipeline_verified_hdr10plus is True
    warnings = [message for level, message in logger.messages if level == "warn"]
    assert len(warnings) == 1
    assert "HDR10+-Policy bleibt unverändert" in warnings[0]


def test_same_parser_text_outside_source_rpu_extraction_does_not_fallback():
    failure = PipelineExecutionResult(
        success=False,
        failure_stage="STEP 6/7 RPU-Injektion",
        failure_reason="dovi_tool.exe fehlgeschlagen (rc=1)",
        tool_output="Error: Invalid RPU last byte: 248",
        tool="dovi_tool.exe",
        command="dovi_tool.exe inject-rpu ...",
    )
    svc, _temp_state, logger, planning, executor = _services(failure)
    ctx = _ctx()

    with pytest.raises(RuntimeError, match="STEP 6/7 RPU-Injektion"):
        svc.process(ctx, {})

    assert len(executor.requests) == 1
    assert planning.overrides == []
    assert not [message for level, message in logger.messages if level == "warn"]


def test_other_dovi_tool_extract_failure_stays_hard_failure():
    failure = PipelineExecutionResult(
        success=False,
        failure_stage="STEP 3/7 RPU-Extraktion",
        failure_reason="STEP 3/7 RPU-Extraktion: dovi_tool.exe fehlgeschlagen (rc=1)",
        tool_output="Error: No track found for ID 0",
        tool="dovi_tool.exe",
        command="dovi_tool.exe extract-rpu ...",
    )
    svc, _temp_state, logger, planning, executor = _services(failure)
    ctx = _ctx()

    with pytest.raises(RuntimeError, match="RPU-Extraktion"):
        svc.process(ctx, {})

    assert len(executor.requests) == 1
    assert planning.overrides == []
    assert not [message for level, message in logger.messages if level == "warn"]
