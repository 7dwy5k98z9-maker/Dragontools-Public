from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace


def _helper(tmp_path):
    from dragontools.worker.dv_runtime_models import DVTempState
    from dragontools.worker.hdrplus_conversion import HDRPlusConversionHelper

    tools = SimpleNamespace(
        ffmpeg="ffmpeg",
        hdr10plus_tool="hdr10plus_tool",
    )
    progress = SimpleNamespace(worker=None, probe_ms=lambda *_: 100_000)
    return HDRPlusConversionHelper(
        tools=tools,
        log=lambda *_: None,
        codec="h265",
        crf=23,
        preset="medium",
        encoder_options={"encoder": "cpu"},
        progress_runner=progress,
        temp_state=DVTempState(),
    )


def test_final_hdr10plus_verification_extracts_from_finished_container(tmp_path, monkeypatch):
    helper = _helper(tmp_path)
    output = tmp_path / "film.mkv"
    output.write_bytes(b"m" * 2048)
    expected = tmp_path / "metadata.json"
    expected.write_text(json.dumps({"SceneInfo": [{"LuminanceParameters": {"AverageRGB": 1}}]}), encoding="utf-8")
    seen = {}

    def fake_run(cmd, *, label, tool_name):
        seen["cmd"] = list(cmd)
        Path(cmd[-1]).write_bytes(b"h" * 2048)
        return True

    class FakeService:
        def verify_metadata(self, run_cmd, *, source_stream, scratch_json, expected_json):
            seen["source_stream"] = Path(source_stream)
            seen["expected_json"] = Path(expected_json)
            return True

    monkeypatch.setattr(helper, "_run_hdrplus_tool", fake_run)
    helper._hdr10plus_service = FakeService()

    assert helper._verify_final_hdr10plus(str(output), expected) is True
    assert "-i" in seen["cmd"]
    assert seen["cmd"][seen["cmd"].index("-i") + 1] == str(output)
    assert seen["source_stream"].name == "final_verify.hevc"
    assert seen["expected_json"] == expected


def test_hdrplus_run_fails_if_final_semantic_verification_fails(tmp_path, monkeypatch):
    helper = _helper(tmp_path)
    output = tmp_path / "film.mkv"
    source = tmp_path / "source.mkv"
    source.write_bytes(b"s" * 2048)
    media = SimpleNamespace(primary_video=SimpleNamespace(codec="hevc"))

    def fake_extract(_source, target):
        Path(target).write_bytes(b"x" * 2048)
        return True

    def fake_meta(_source, target):
        Path(target).write_text(json.dumps({"SceneInfo": [1]}), encoding="utf-8")
        return True

    def fake_inject(_encoded, _meta, target):
        Path(target).write_bytes(b"i" * 2048)
        return True

    def fake_mux(_injected, _encoded, target):
        Path(target).write_bytes(b"o" * 2048)
        return True

    def fake_run_p(cmd, _input, _duration):
        Path(cmd[-1]).write_bytes(b"e" * 2048)
        return 0

    helper._progress.run_p = fake_run_p
    monkeypatch.setattr(helper, "_extract_hevc_annexb", fake_extract)
    monkeypatch.setattr(helper, "_extract_hdr10plus_metadata", fake_meta)
    monkeypatch.setattr(helper, "_inject_hdr10plus_metadata", fake_inject)
    monkeypatch.setattr(helper, "_mux_hdrplus_mkv", fake_mux)
    monkeypatch.setattr(helper, "_verify_final_hdr10plus", lambda *_: False)

    ok = helper.run(
        str(source), str(output), media,
        vf_args=[], audio_args=["-an"], audio_input_args=[], sn=["-sn"], crop=None,
    )

    assert ok is False
    assert helper.last_final_hdr10plus_verified is False


def test_hdrplus_run_marks_final_semantic_verification_success(tmp_path, monkeypatch):
    helper = _helper(tmp_path)
    output = tmp_path / "film.mkv"
    source = tmp_path / "source.mkv"
    source.write_bytes(b"s" * 2048)
    media = SimpleNamespace(primary_video=SimpleNamespace(codec="hevc"))

    def fake_extract(_source, target):
        Path(target).write_bytes(b"x" * 2048)
        return True

    def fake_meta(_source, target):
        Path(target).write_text(json.dumps({"SceneInfo": [1]}), encoding="utf-8")
        return True

    def fake_inject(_encoded, _meta, target):
        Path(target).write_bytes(b"i" * 2048)
        return True

    def fake_mux(_injected, _encoded, target):
        Path(target).write_bytes(b"o" * 2048)
        return True

    def fake_run_p(cmd, _input, _duration):
        Path(cmd[-1]).write_bytes(b"e" * 2048)
        return 0

    helper._progress.run_p = fake_run_p
    monkeypatch.setattr(helper, "_extract_hevc_annexb", fake_extract)
    monkeypatch.setattr(helper, "_extract_hdr10plus_metadata", fake_meta)
    monkeypatch.setattr(helper, "_inject_hdr10plus_metadata", fake_inject)
    monkeypatch.setattr(helper, "_mux_hdrplus_mkv", fake_mux)
    monkeypatch.setattr(helper, "_verify_final_hdr10plus", lambda *_: True)

    ok = helper.run(
        str(source), str(output), media,
        vf_args=[], audio_args=["-an"], audio_input_args=[], sn=["-sn"], crop=None,
    )

    assert ok is True
    assert helper.last_final_hdr10plus_verified is True


def test_hdr10plus_semantic_compare_ignores_toolinfo_and_derived_scene_summary():
    from dragontools.worker.hdr10plus_bitstream_service import HDR10PlusBitstreamService

    expected = {
        "ToolInfo": {"Version": "old"},
        "SceneInfoSummary": {"SceneCount": 1, "SceneFirstFrameIndex": [0]},
        "SceneInfo": [{"LuminanceParameters": {"AverageRGB": 123}}],
    }
    actual = {
        "ToolInfo": {"Version": "new"},
        "SceneInfoSummary": {"SceneCount": 1, "SceneFirstFrameIndex": [1]},
        "SceneInfo": [{"LuminanceParameters": {"AverageRGB": 123}}],
    }

    assert HDR10PlusBitstreamService._semantic_payload(expected) == HDR10PlusBitstreamService._semantic_payload(actual)


def test_hdr10plus_semantic_compare_still_rejects_changed_dynamic_scene_data():
    from dragontools.worker.hdr10plus_bitstream_service import HDR10PlusBitstreamService

    expected = {"SceneInfo": [{"LuminanceParameters": {"AverageRGB": 123}}]}
    actual = {"SceneInfo": [{"LuminanceParameters": {"AverageRGB": 124}}]}

    assert HDR10PlusBitstreamService._semantic_payload(expected) != HDR10PlusBitstreamService._semantic_payload(actual)


def test_hdrplus_tool_runner_accepts_success_and_configured_warning_rc(tmp_path, monkeypatch):
    from dragontools.worker.tool_runner import ToolRunResult

    helper = _helper(tmp_path)
    log_lines = []
    helper._log_fn = lambda message, level="info": log_lines.append((message, level))

    results = iter([
        ToolRunResult(command=["tool"], returncode=0),
        ToolRunResult(command=["tool"], returncode=1, stderr="warning"),
    ])
    monkeypatch.setattr(
        "dragontools.worker.hdrplus_conversion.run_tool",
        lambda command, **_kwargs: next(results),
    )

    assert helper._run_hdrplus_tool(["tool"], label="ok", tool_name="tool") is True
    assert helper._run_hdrplus_tool(
        ["tool"],
        label="warn",
        tool_name="tool",
        accepted_returncodes=(0, 1),
    ) is True
    assert any(level == "warn" and "rc=1" in message for message, level in log_lines)


def test_hdrplus_tool_runner_rejects_unaccepted_returncode(tmp_path, monkeypatch):
    from dragontools.worker.tool_runner import ToolRunResult

    helper = _helper(tmp_path)
    monkeypatch.setattr(
        "dragontools.worker.hdrplus_conversion.run_tool",
        lambda command, **_kwargs: ToolRunResult(command=list(command), returncode=2, stderr="failed"),
    )
    failures = []
    monkeypatch.setattr(
        "dragontools.worker.hdrplus_conversion.log_tool_failure",
        lambda result, **kwargs: failures.append((result.returncode, kwargs.get("tool_name"))),
    )

    assert helper._run_hdrplus_tool(["tool"], label="fail", tool_name="tool") is False
    assert failures == [(2, "tool")]


def test_hdrplus_mux_runner_honors_accepted_warning_returncode(tmp_path, monkeypatch):
    from dragontools.worker.tool_runner import ToolRunResult

    helper = _helper(tmp_path)
    monkeypatch.setattr(
        "dragontools.worker.hdrplus_conversion.run_tool",
        lambda command, **_kwargs: ToolRunResult(command=list(command), returncode=1, stderr="mkvmerge warning"),
    )

    assert helper._run_mux_tool(
        ["mkvmerge"],
        label="mkv",
        tool_name="mkvmerge",
        accepted_returncodes=(0, 1),
    ) is True


def test_subtitle_default_schema_matches_central_schema_and_is_idempotent():
    from dragontools.core.config_migration import current_schema_version
    from dragontools.rules.subtitle_rules import migrate_subtitle_rules

    root = Path(__file__).resolve().parents[1]
    default_rules = json.loads(
        (root / "config" / "default_subtitle_rules.json").read_text(encoding="utf-8")
    )

    assert default_rules["_schema_version"] == current_schema_version("subtitle_rules") == 4
    migrated = migrate_subtitle_rules(default_rules)
    assert migrated["_schema_version"] == 4
    assert migrate_subtitle_rules(migrated) == migrated
