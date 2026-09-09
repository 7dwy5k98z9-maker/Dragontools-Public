from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace


def _worker_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "worker"


def _class_node(path: Path, name: str) -> ast.ClassDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)


def test_hdrplus_coordinator_stays_below_release_complexity_ceiling():
    worker = _worker_dir()
    coordinator = worker / "hdrplus_conversion.py"
    mux_service = worker / "hdrplus_mux_service.py"
    tool_runner = worker / "hdrplus_tool_runner.py"

    assert len(coordinator.read_text(encoding="utf-8").splitlines()) <= 650
    assert len(mux_service.read_text(encoding="utf-8").splitlines()) <= 250
    assert len(tool_runner.read_text(encoding="utf-8").splitlines()) <= 220


def test_hdrplus_coordinator_does_not_reimplement_mux_or_metadata_json_parsing():
    source = (_worker_dir() / "hdrplus_conversion.py").read_text(encoding="utf-8")

    assert "json.loads(" not in source
    assert "mkvmerge\", \"-o" not in source
    assert "\"-inter\", \"500\"" not in source
    assert ".extract_metadata(" in source
    assert ".inject_metadata(" in source


def test_hdrplus_tool_calls_are_confined_to_injected_runner_bridge():
    path = _worker_dir() / "hdrplus_conversion.py"
    cls = _class_node(path, "HDRPlusConversionHelper")

    direct_run_tool_methods = []
    for method in (node for node in cls.body if isinstance(node, ast.FunctionDef)):
        for call in ast.walk(method):
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "run_tool":
                direct_run_tool_methods.append(method.name)

    # Nur __init__ darf die dynamische Abhängigkeit in den ToolRunner injizieren.
    assert direct_run_tool_methods == ["__init__"]


def test_hdrplus_tool_runner_records_command_and_failure_diagnostics():
    from dragontools.worker.dv_runtime_models import DVTempState
    from dragontools.worker.hdrplus_tool_runner import HDRPlusToolRunner
    from dragontools.worker.tool_runner import ToolRunResult

    state = DVTempState()
    failures = []
    runner = HDRPlusToolRunner(
        run_tool_fn=lambda command, **_kwargs: ToolRunResult(
            command=list(command), returncode=2, stderr="broken"
        ),
        log_tool_failure_fn=lambda result, **kwargs: failures.append(
            (result.returncode, kwargs["tool_name"])
        ),
        log=lambda *_: None,
        temp_state=state,
    )

    assert runner.run_hdrplus(["hdr10plus_tool", "extract"], label="extract", tool_name="hdr10plus_tool") is False
    assert state.last_tool == "hdr10plus_tool"
    assert "hdr10plus_tool" in state.last_command
    assert state.failure_stage == "extract"
    assert "rc=2" in state.failure_reason
    assert "broken" in state.stderr
    assert failures == [(2, "hdr10plus_tool")]


def test_hdrplus_metadata_wrappers_use_existing_bitstream_service(tmp_path):
    from dragontools.worker.dv_runtime_models import DVTempState
    from dragontools.worker.hdrplus_conversion import HDRPlusConversionHelper

    tools = SimpleNamespace(ffmpeg="ffmpeg", hdr10plus_tool="hdr10plus_tool")
    progress = SimpleNamespace(worker=None, probe_ms=lambda *_: 1)
    helper = HDRPlusConversionHelper(
        tools=tools,
        log=lambda *_: None,
        codec="h265",
        crf=23,
        preset="medium",
        encoder_options={},
        progress_runner=progress,
        temp_state=DVTempState(),
    )
    seen = []

    class MetadataService:
        def extract_metadata(self, run_cmd, *, source_stream, output_json):
            seen.append(("extract", source_stream, output_json, callable(run_cmd)))
            return True

        def inject_metadata(self, run_cmd, *, input_hevc, metadata_json, output_hevc):
            seen.append(("inject", input_hevc, metadata_json, output_hevc, callable(run_cmd)))
            return True

    helper._hdr10plus_service = MetadataService()
    assert helper._extract_hdr10plus_metadata("source.mkv", str(tmp_path / "meta.json")) is True
    assert helper._inject_hdr10plus_metadata("encoded.hevc", "meta.json", "injected.hevc") is True

    assert seen[0][0] == "extract" and seen[0][3] is True
    assert seen[1][0] == "inject" and seen[1][4] is True


def test_hdrplus_execute_does_not_mutate_default_encoder_state(monkeypatch):
    from dragontools.worker.dv_runtime_models import DVTempState
    from dragontools.worker.hdrplus_conversion import HDRPlusConversionHelper
    from dragontools.worker.hdrplus_runtime_models import HDRPlusPipelineOutcome

    tools = SimpleNamespace(ffmpeg="ffmpeg", hdr10plus_tool="hdr10plus_tool")
    progress = SimpleNamespace(worker=None, probe_ms=lambda *_: 1)
    helper = HDRPlusConversionHelper(
        tools=tools,
        log=lambda *_: None,
        codec="h265",
        crf=23,
        preset="medium",
        encoder_options={"encoder": "cpu"},
        progress_runner=progress,
        temp_state=DVTempState(),
    )
    before = (helper._codec, helper._crf, helper._preset, dict(helper._encoder_options))
    seen = {}

    def fake_run_pipeline(**kwargs):
        seen["encoder"] = kwargs["encoder"]
        return HDRPlusPipelineOutcome(True, verified_hdr10plus=True)

    monkeypatch.setattr(helper, "_run_pipeline", fake_run_pipeline)
    request = SimpleNamespace(
        plan=SimpleNamespace(vf_args=[], audio_args=["-an"], audio_input_args=[], sn=["-sn"], crop=None),
        codec="h265",
        crf=17,
        preset="slow",
        encoder_options={"encoder": "gpu"},
        input_path="input.mkv",
        output_path="output.mkv",
        media_info=SimpleNamespace(),
        container="mkv",
        override={},
    )

    result = helper.execute(request)

    assert result.success is True
    assert (helper._codec, helper._crf, helper._preset, dict(helper._encoder_options)) == before
    assert seen["encoder"].crf == 17
    assert seen["encoder"].preset == "slow"
    assert dict(seen["encoder"].encoder_options) == {"encoder": "gpu"}


def test_hdrplus_execution_context_defensively_freezes_job_options():
    from dragontools.worker.hdrplus_runtime_models import HDRPlusEncoderConfig, HDRPlusExecutionContext

    raw_options = {"aq": 2}
    raw_override = {"subtitle_mode": "auto"}
    encoder = HDRPlusEncoderConfig.create(
        codec="h265", crf=20, preset="medium", encoder_options=raw_options
    )
    context = HDRPlusExecutionContext.create(
        input_path="in.mkv",
        output_path="out.mkv",
        media_info=SimpleNamespace(),
        vf_args=[], audio_args=[], audio_input_args=[], subtitle_args=[],
        crop=None, container="mkv", override=raw_override, encoder=encoder,
    )
    raw_options["aq"] = 99
    raw_override["subtitle_mode"] = "changed"

    assert dict(context.encoder.encoder_options) == {"aq": 2}
    assert dict(context.override) == {"subtitle_mode": "auto"}


def test_hdrplus_new_services_stay_qt_free_and_coordinator_methods_bounded():
    worker = _worker_dir()
    files = [
        worker / "hdrplus_pipeline_coordinator.py",
        worker / "hdrplus_encode_service.py",
        worker / "hdrplus_stream_service.py",
        worker / "hdrplus_runtime_models.py",
    ]
    for path in files:
        source = path.read_text(encoding="utf-8")
        assert "PyQt" not in source
        assert "from PySide" not in source

    coordinator = _class_node(worker / "hdrplus_pipeline_coordinator.py", "HDRPlusPipelineCoordinator")
    method_sizes = {
        node.name: node.end_lineno - node.lineno + 1
        for node in coordinator.body
        if isinstance(node, ast.FunctionDef)
    }
    assert max(method_sizes.values()) <= 80
    assert method_sizes["run"] <= 80


def test_hdrplus_helper_run_is_now_thin_facade():
    cls = _class_node(_worker_dir() / "hdrplus_conversion.py", "HDRPlusConversionHelper")
    run = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "run")
    execute = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "execute")
    assert run.end_lineno - run.lineno + 1 <= 35
    assert execute.end_lineno - execute.lineno + 1 <= 55


def test_hdrplus_new_job_clears_stale_tool_diagnostics_before_preflight():
    from dragontools.worker.dv_runtime_models import DVTempState
    from dragontools.worker.hdrplus_conversion import HDRPlusConversionHelper

    state = DVTempState(
        stderr="old stderr",
        failure_reason="old failure",
        failure_stage="old stage",
        last_tool="old tool",
        last_command="old command",
    )
    tools = SimpleNamespace(ffmpeg="ffmpeg", hdr10plus_tool="hdr10plus_tool")
    helper = HDRPlusConversionHelper(
        tools=tools,
        log=lambda *_: None,
        codec="h265",
        crf=23,
        preset="medium",
        encoder_options={},
        progress_runner=SimpleNamespace(worker=None, probe_ms=lambda *_: 1),
        temp_state=state,
    )
    request = SimpleNamespace(
        plan=SimpleNamespace(vf_args=[], audio_args=["-an"], audio_input_args=[], sn=["-sn"], crop=None),
        codec="h264",
        crf=23,
        preset="medium",
        encoder_options={},
        input_path="input.mkv",
        output_path="output.mkv",
        media_info=SimpleNamespace(primary_video=SimpleNamespace(codec="hevc")),
        container="mkv",
        override={},
    )

    result = helper.execute(request)

    assert result.success is False
    assert result.failure_reason == "HDR10+-Pipeline fehlgeschlagen."
    assert result.failure_stage == "HDR10+"
    assert result.tool_output == ""
    assert result.tool == ""
    assert result.command == ""
