from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from dragontools.worker.hdr10plus_generator_client import HDR10PlusGeneratorClient
from dragontools.worker.tool_runner import ToolRunResult


def test_hdr10plus_client_streams_generator_progress_into_dragontools_log(tmp_path):
    exe = tmp_path / "HDRPlusGenerator.exe"
    exe.write_bytes(b"x")
    source = tmp_path / "movie.mkv"
    source.write_bytes(b"video")
    output = tmp_path / "hdr10plus.json"
    logs: list[tuple[str, str]] = []

    def fake_run(command, **kwargs):
        callback = kwargs.get("stderr_line")
        assert callable(callback)
        callback("HDR10+ scan: 24000/172800 frames (13.9%) | 6.6 fps | elapsed 01:00:00 | ETA 06:13:38")
        output.write_text('{"SceneInfo":[{"SequenceFrameIndex":0}]}', encoding="utf-8")
        return ToolRunResult(
            command=list(command),
            returncode=0,
            stdout=json.dumps({"success": True, "frames": 1, "scenes": 1}),
        )

    result = HDR10PlusGeneratorClient(
        str(exe),
        log=lambda message, level="info": logs.append((str(message), str(level))),
        run_tool_fn=fake_run,
    ).analyze(source, output)

    assert result.success is True
    assert any("13.9%" in message and "ETA 06:13:38" in message for message, _ in logs)


def test_dv_pipeline_releases_encode_slot_exactly_once_after_success(monkeypatch):
    import dragontools.worker.dv_pipeline_stages as module
    from dragontools.worker.dv_pipeline_stages import DVPipelineStages

    class VideoService:
        def encode_video(self, state, runner):
            return True

    monkeypatch.setattr(module, "_video_service", lambda _owner: VideoService())
    calls: list[object] = []
    stages = object.__new__(DVPipelineStages)
    stages._encode_complete = lambda state: calls.append(state)
    state = SimpleNamespace(encode_slot_released=False)

    assert stages._encode_video(state, object()) is True
    assert stages._encode_video(state, object()) is True
    assert calls == [state]
    assert state.encode_slot_released is True


def test_dv_pipeline_does_not_release_slot_when_encode_fails(monkeypatch):
    import dragontools.worker.dv_pipeline_stages as module
    from dragontools.worker.dv_pipeline_stages import DVPipelineStages

    class VideoService:
        def encode_video(self, state, runner):
            return False

    monkeypatch.setattr(module, "_video_service", lambda _owner: VideoService())
    calls: list[object] = []
    stages = object.__new__(DVPipelineStages)
    stages._encode_complete = lambda state: calls.append(state)
    state = SimpleNamespace(encode_slot_released=False)

    assert stages._encode_video(state, object()) is False
    assert calls == []
    assert state.encode_slot_released is False


def test_dv_encode_complete_emits_dedicated_stage_event_only_for_overlap_worker():
    from dragontools.worker.dv_processing_pipeline import DVProcessingPipeline

    events: list[tuple[str, str, str]] = []
    logs: list[str] = []
    worker = SimpleNamespace(
        _enable_dv_encode_overlap=True,
        emit_encode_stage_complete=lambda *args: events.append(tuple(args)),
    )
    pipeline = object.__new__(DVProcessingPipeline)
    pipeline._worker = worker
    pipeline._log_fn = lambda message, level="info": logs.append(str(message))
    state = SimpleNamespace(request=SimpleNamespace(input_path="in.mkv", output_path="out.mkv"))

    pipeline._notify_encode_complete(state)

    assert events == [("in.mkv", "out.mkv")]
    assert any("Encode-Slot" in line for line in logs)


def test_multi_file_single_encode_slot_uses_parallel_coordinator(monkeypatch):
    from dragontools.gui.conversion_worker_factory import ConversionConfigBuilder, ConversionWorkerFactory

    class Spin:
        def value(self): return 23
    class Text:
        def currentText(self): return "medium"
    class Scale:
        def currentText(self): return "original"
    class Check:
        def isChecked(self): return False
    class FakeParallel:
        def __init__(self, files, config, *, parallel_jobs, parent=None):
            self.files = list(files); self.parallel_jobs = parallel_jobs; self.config = config
    class FakeSingle:
        def __init__(self, *args, **kwargs):
            raise AssertionError("multi-file queue must use the coordinator even with one encode slot")

    monkeypatch.setattr(ConversionConfigBuilder, "subtitle_rules", lambda self: {})
    builder = ConversionConfigBuilder(
        state=SimpleNamespace(file_overrides={}),
        ui=SimpleNamespace(crf_spin=Spin(), preset_combo=Text(), scale_combo=Scale(), over_cb=Check(), strip_cb=Check()),
        default_codec="h265",
        collect_encoder_options=lambda: {"encoder": "nvenc"},
        get_target_paths=lambda: {},
        log=lambda *_a, **_k: None,
    )
    factory = ConversionWorkerFactory(
        config_builder=builder,
        qt_parent=None,
        converter_cls=FakeSingle,
        parallel_converter_cls=FakeParallel,
    )

    worker = factory.create_converter(["a.mkv", "b.mkv"], parallel_jobs=1)
    assert isinstance(worker, FakeParallel)
    assert worker.parallel_jobs == 1
    assert worker.files == ["a.mkv", "b.mkv"]


def test_release_build_smoke_is_timeout_bounded_and_restores_previous_build_on_failure():
    root = Path(__file__).resolve().parents[2]
    text = (root / "build_v9.bat").read_text(encoding="utf-8")
    assert "WaitForExit(90000)" in text
    assert "Frozen-Smoke Timeout nach 90s" in text
    assert "BACKUP_DIST_ROOT" in text
    assert "Vorhandener funktionierender Build" in text
    assert 'move /Y "%BACKUP_DIST_ROOT%" "%DIST_ROOT%"' in text


def test_release_tag_ci_uses_canonical_builders():
    root = Path(__file__).resolve().parents[2]
    workflow = (root / ".github/workflows/tests.yml").read_text(encoding="utf-8")
    assert 'cmd /c "dragon_hdr10plus_generator\\build.bat"' in workflow
    assert 'cmd /c "build_v9.bat"' in workflow
    assert "DRAGONTOOLS_THIRD_PARTY_ROOT" in workflow
    assert "python -m pip install -r requirements-build.txt" in workflow
