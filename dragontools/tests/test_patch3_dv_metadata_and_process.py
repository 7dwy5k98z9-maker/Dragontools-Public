from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace


def test_dv_encode_forces_frame_passthrough(tmp_path):
    from dragontools.worker.dv_encode_command import build_dv_encode_command
    from dragontools.worker.dv_runtime_models import DVEncoderConfig

    plan = build_dv_encode_command(
        ffmpeg_path="ffmpeg",
        encoder_config=DVEncoderConfig(codec="h265", crf=23, preset="p6", options={}),
        input_path="input.mkv",
        p8_hevc=tmp_path / "p8.hevc",
        output_hevc=tmp_path / "out.hevc",
        vf_args=["-map", "0:v:0"],
        profile_major=8,
    )
    assert "-fps_mode" in plan.command
    idx = plan.command.index("-fps_mode")
    assert plan.command[idx + 1] == "passthrough"


def test_physical_crop_writes_zero_level5_offsets(tmp_path):
    from dragontools.worker.dv_level5_editor import DVLevel5Editor

    rpu_orig = tmp_path / "orig.rpu"
    rpu_orig.write_bytes(b"rpu")
    rpu_final = tmp_path / "final.rpu"
    edit_json = tmp_path / "level5.json"
    logs = []

    def run_cmd(cmd, **kwargs):
        if "editor" in cmd:
            rpu_final.write_bytes(b"edited")
            return SimpleNamespace(returncode=0)
        if "export" in cmd:
            target = Path(cmd[-1].split("=", 1)[1])
            target.write_text(
                json.dumps({
                    "active_area": {
                        "crop": True,
                        "presets": [
                            {"id": 0, "left": 0, "right": 0, "top": 0, "bottom": 0}
                        ],
                        "edits": {"all": 0},
                    }
                }),
                encoding="utf-8",
            )
            return 0
        return 1

    editor = DVLevel5Editor(dovi_tool_path="dovi_tool", log=lambda m, l="info": logs.append((l, m)))
    result = editor.resolve_rpu_for_crop(
        run_cmd,
        crop="crop=3840:1596:0:282",
        media_info=SimpleNamespace(primary_video=SimpleNamespace(width=3840, height=2160)),
        rpu_orig=rpu_orig,
        rpu_final=rpu_final,
        edit_json=edit_json,
        save_failure_artifacts=lambda *args, **kwargs: tmp_path / "fail",
    )

    assert result == rpu_final
    payload = json.loads(edit_json.read_text(encoding="utf-8"))
    assert payload == {"active_area": {"crop": True}}


def test_dv_command_runner_uses_shared_process_control(monkeypatch):
    import dragontools.worker.dv_command_runner as module

    worker = SimpleNamespace()
    seen = {}

    def fake_run_tool(command, **kwargs):
        seen["command"] = command
        seen.update(kwargs)
        return SimpleNamespace(
            returncode=0,
            stdout="",
            stderr="",
            aborted=False,
            timed_out=False,
            combined_output="",
        )

    monkeypatch.setattr(module, "run_tool", fake_run_tool)
    runner = module.DVCommandRunner(
        log=lambda *_: None,
        verbose_log=lambda *_: None,
        no_window_kwargs=lambda: {},
        worker=worker,
    )
    assert runner.run(["dovi_tool", "info", "-s", "x.rpu"], timeout=12) == 0
    assert seen["worker"] is worker
    assert seen["timeout_s"] == 12


def _stages_for_verification(tmp_path):
    from dragontools.worker.dv_pipeline_stages import DVPipelineStages

    stages = DVPipelineStages.__new__(DVPipelineStages)
    stages._tools = SimpleNamespace(dovi_tool="dovi_tool", ffprobe="ffprobe")
    stages._temp_state = SimpleNamespace(
        record_failure=lambda **kwargs: setattr(stages, "failure", kwargs)
    )
    stages._log = lambda *args, **kwargs: None
    stages._vlog = lambda *args, **kwargs: None
    stages._assert_nonempty_file = lambda path, label: path.exists() and path.stat().st_size > 0
    return stages


def test_rpu_frame_mismatch_blocks_injection(tmp_path, monkeypatch):
    stages = _stages_for_verification(tmp_path)
    monkeypatch.setattr(stages, "_probe_rpu_frame_count", lambda *args, **kwargs: 100)
    monkeypatch.setattr(stages, "_probe_hevc_frame_count", lambda *args, **kwargs: 99)
    assert stages._validate_rpu_frame_parity(
        SimpleNamespace(),
        rpu_path=tmp_path / "a.rpu",
        hevc_path=tmp_path / "a.hevc",
    ) is False
    assert "Frame-Mismatch" in stages.failure["reason"]


def test_rpu_post_injection_hash_mismatch_is_rejected(tmp_path):
    stages = _stages_for_verification(tmp_path)
    expected = tmp_path / "expected.rpu"
    scratch = tmp_path / "verify.rpu"
    injected = tmp_path / "injected.hevc"
    expected.write_bytes(b"expected")
    injected.write_bytes(b"video")

    class FakeRpuService:
        @staticmethod
        def extract_rpu(run_cmd, *, input_hevc, output_rpu):
            output_rpu.write_bytes(b"different")
            return True

    stages._rpu_service = FakeRpuService()
    runner = SimpleNamespace(adapter=lambda **kwargs: (lambda *args, **kw: 0))
    assert stages._verify_injected_rpu(
        runner,
        injected_hevc=injected,
        expected_rpu=expected,
        scratch_rpu=scratch,
    ) is False
    assert "RPU-Inhalt" in stages.failure["reason"]


def test_physical_left_right_crop_is_zeroed_in_rpu_for_mkv_and_mp4_logic(tmp_path):
    """Regressionsfall: 3840 -> 3240 (300 px links/rechts) darf nicht doppelt croppen."""
    from dragontools.worker.dv_level5_editor import DVLevel5Editor

    for container in ("mkv", "mp4"):
        root = tmp_path / container
        root.mkdir()
        rpu_orig = root / "orig.rpu"
        rpu_orig.write_bytes(b"rpu")
        rpu_final = root / "final.rpu"
        edit_json = root / "level5.json"
        seen = []

        def run_cmd(cmd, **kwargs):
            seen.append(list(cmd))
            if "editor" in cmd:
                rpu_final.write_bytes(b"edited")
                return SimpleNamespace(returncode=0)
            if "export" in cmd:
                target = Path(cmd[-1].split("=", 1)[1])
                target.write_text(json.dumps({
                    "active_area": {
                        "crop": True,
                        "presets": [
                            {"id": 0, "left": 0, "right": 0, "top": 0, "bottom": 0}
                        ],
                        "edits": {"0-100": 0},
                    }
                }), encoding="utf-8")
                return 0
            return 1

        editor = DVLevel5Editor(dovi_tool_path="dovi_tool", log=lambda *_: None)
        result = editor.resolve_rpu_for_crop(
            run_cmd,
            crop="crop=3240:2160:300:0",
            media_info=SimpleNamespace(primary_video=SimpleNamespace(width=3840, height=2160)),
            rpu_orig=rpu_orig,
            rpu_final=rpu_final,
            edit_json=edit_json,
            save_failure_artifacts=lambda *args, **kwargs: root / "fail",
        )

        assert result == rpu_final
        assert json.loads(edit_json.read_text(encoding="utf-8")) == {
            "active_area": {"crop": True}
        }
        assert any("editor" in cmd for cmd in seen)
        assert any("export" in cmd for cmd in seen)


def test_physical_crop_fails_closed_if_final_rpu_still_has_nonzero_l5(tmp_path):
    from dragontools.worker.dv_level5_editor import DVLevel5Editor

    rpu_orig = tmp_path / "orig.rpu"
    rpu_orig.write_bytes(b"rpu")
    rpu_final = tmp_path / "final.rpu"
    edit_json = tmp_path / "level5.json"
    failures = []

    def run_cmd(cmd, **kwargs):
        if "editor" in cmd:
            rpu_final.write_bytes(b"edited-but-wrong")
            return SimpleNamespace(returncode=0)
        if "export" in cmd:
            target = Path(cmd[-1].split("=", 1)[1])
            target.write_text(json.dumps({
                "active_area": {
                    "crop": True,
                    "presets": [
                        {"id": 0, "left": 300, "right": 300, "top": 0, "bottom": 0}
                    ],
                    "edits": {"0-100": 0},
                }
            }), encoding="utf-8")
            return 0
        return 1

    editor = DVLevel5Editor(dovi_tool_path="dovi_tool", log=lambda *_: None)
    result = editor.resolve_rpu_for_crop(
        run_cmd,
        crop="crop=3240:2160:300:0",
        media_info=SimpleNamespace(primary_video=SimpleNamespace(width=3840, height=2160)),
        rpu_orig=rpu_orig,
        rpu_final=rpu_final,
        edit_json=edit_json,
        save_failure_artifacts=lambda *args, **kwargs: failures.append(True) or (tmp_path / "fail"),
    )

    assert result is None
    assert failures == [True]
