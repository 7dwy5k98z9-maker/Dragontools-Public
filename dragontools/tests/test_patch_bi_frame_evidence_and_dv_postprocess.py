from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

from dragontools.worker.dv_postprocess_gate import DVPostprocessGate
from dragontools.worker.frame_count_evidence import FrameCountEvidence, temporal_mapping_for_filters
from dragontools.worker.parallel_child_result_coordinator import ParallelChildResultCoordinator
from dragontools.worker.parallel_converter_state import ParallelQueueState, ParallelResultState, ParallelWorkerRegistry


def test_dv_postprocess_gate_limits_heavy_work_to_four_jobs():
    gate = DVPostprocessGate(4)
    release = threading.Event()
    entered: list[int] = []
    lock = threading.Lock()

    def worker(index: int) -> None:
        assert gate.acquire()
        with lock:
            entered.append(index)
        release.wait(2)
        gate.release()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline and len(entered) < 4:
        time.sleep(0.01)
    assert len(entered) == 4
    assert gate.active == 4
    release.set()
    for thread in threads:
        thread.join(2)
    assert len(entered) == 6
    assert gate.active == 0


def test_encode_stage_complete_is_not_legacy_committed_postprocess_status():
    queue = ParallelQueueState(["a.mkv", "b.mkv"])
    results = ParallelResultState()
    registry = ParallelWorkerRegistry(queue, results)
    class Child:
        def isRunning(self):
            return True
    child = Child()
    registry.active_workers.add(child)
    coordinator = ParallelChildResultCoordinator(registry=registry, queue_state=queue, result_state=results)
    emitted: list[tuple[str, str]] = []
    starts: list[str] = []

    coordinator.on_encode_stage_complete(
        child,
        "a.mkv",
        "a.mkv",
        abort_requested=False,
        start_pending_workers=lambda: starts.append("start"),
        emit_encode_stage_complete=lambda a, b: emitted.append((a, b)),
        emit_aggregate_progress=lambda: None,
        finish_if_done=lambda: None,
    )

    assert emitted == [("a.mkv", "a.mkv")]
    assert "a.mkv" in queue.dv_postprocessing_inputs
    assert "a.mkv" not in queue.postprocessing_inputs
    assert queue.file_progress_pct["a.mkv"] == 90
    assert child not in registry.active_workers
    assert child in registry.postprocessing_workers
    assert starts == ["start"]
    assert queue.aggregate_progress_percent() < 100


def test_frame_evidence_rejects_stale_stream_after_replacement(tmp_path):
    stream = tmp_path / "encoded.hevc"
    stream.write_bytes(b"one")
    evidence = FrameCountEvidence.reliable(
        123,
        source="ffmpeg_encode_progress",
        path=stream,
        stage="encode",
        temporal_mapping="preserved",
    )
    assert evidence.is_reliable_for(stream)
    time.sleep(0.002)
    stream.write_bytes(b"replacement-with-different-size")
    assert not evidence.is_reliable_for(stream)


def test_temporal_mapping_flags_frame_altering_filters_only():
    assert temporal_mapping_for_filters(["-vf", "crop=1920:800,scale=3840:1600"]) == "preserved"
    assert temporal_mapping_for_filters(["-vf", "fps=50,scale=1920:1080"]) == "changed"
    assert temporal_mapping_for_filters(["-vf", "select='not(mod(n,2))',setpts=N/25/TB"]) == "changed"


def test_rpu_parity_uses_reliable_encode_evidence_without_hevc_full_scan(tmp_path):
    from dragontools.worker.dv_dynamic_metadata_service import DVDynamicMetadataService

    hevc = tmp_path / "encoded.hevc"
    rpu = tmp_path / "metadata.rpu"
    hevc.write_bytes(b"video")
    rpu.write_bytes(b"rpu")
    evidence = FrameCountEvidence.reliable(
        100,
        source="ffmpeg_encode_progress",
        path=hevc,
        stage="encode",
        temporal_mapping="preserved",
    )
    temp = SimpleNamespace(record_failure=lambda **kw: setattr(temp, "failure", kw))
    service = DVDynamicMetadataService(
        tools=SimpleNamespace(ffprobe="ffprobe", dovi_tool="dovi_tool"),
        temp_state=temp,
        audio_mux_service=None,
        rpu_service=None,
        hdr10plus_service=None,
        generator_client=None,
        level5_editor=None,
        failure_recovery=None,
        log=lambda *_a, **_k: None,
        verbose_log=lambda *_a, **_k: None,
        assert_nonempty_file=lambda *_a, **_k: True,
    )
    full_scan_called = []
    assert service.validate_rpu_frame_parity(
        SimpleNamespace(),
        rpu_path=rpu,
        hevc_path=hevc,
        frame_evidence=evidence,
        probe_rpu_frame_count=lambda *_a, **_k: 100,
        probe_hevc_frame_count=lambda *_a, **_k: full_scan_called.append(True) or 999,
    )
    assert full_scan_called == []


def test_rpu_parity_does_not_accept_estimate_as_exact(tmp_path):
    from dragontools.worker.dv_dynamic_metadata_service import DVDynamicMetadataService

    hevc = tmp_path / "encoded.hevc"
    rpu = tmp_path / "metadata.rpu"
    hevc.write_bytes(b"video")
    rpu.write_bytes(b"rpu")
    estimate = FrameCountEvidence.estimated(
        100,
        source="duration_x_fps",
        path=hevc,
        stage="preflight",
    )
    service = DVDynamicMetadataService(
        tools=SimpleNamespace(ffprobe="ffprobe", dovi_tool="dovi_tool"),
        temp_state=SimpleNamespace(record_failure=lambda **_kw: None),
        audio_mux_service=None,
        rpu_service=None,
        hdr10plus_service=None,
        generator_client=None,
        level5_editor=None,
        failure_recovery=None,
        log=lambda *_a, **_k: None,
        verbose_log=lambda *_a, **_k: None,
        assert_nonempty_file=lambda *_a, **_k: True,
    )
    # No fast metadata value -> safe fallback, not a false exact equality.
    assert service.validate_rpu_frame_parity(
        SimpleNamespace(),
        rpu_path=rpu,
        hevc_path=hevc,
        frame_evidence=estimate,
        probe_rpu_frame_count=lambda *_a, **_k: 100,
        probe_hevc_frame_count=lambda *_a, **_k: None,
    )


def test_temporal_mapping_change_blocks_dv_even_with_equal_count(tmp_path):
    from dragontools.worker.dv_dynamic_metadata_service import DVDynamicMetadataService

    hevc = tmp_path / "encoded.hevc"
    rpu = tmp_path / "metadata.rpu"
    hevc.write_bytes(b"video")
    rpu.write_bytes(b"rpu")
    evidence = FrameCountEvidence.reliable(
        100,
        source="ffmpeg_encode_progress",
        path=hevc,
        stage="encode",
        temporal_mapping="changed",
    )
    temp = SimpleNamespace(record_failure=lambda **kw: setattr(temp, "failure", kw))
    service = DVDynamicMetadataService(
        tools=SimpleNamespace(ffprobe="ffprobe", dovi_tool="dovi_tool"),
        temp_state=temp,
        audio_mux_service=None,
        rpu_service=None,
        hdr10plus_service=None,
        generator_client=None,
        level5_editor=None,
        failure_recovery=None,
        log=lambda *_a, **_k: None,
        verbose_log=lambda *_a, **_k: None,
        assert_nonempty_file=lambda *_a, **_k: True,
    )
    assert not service.validate_rpu_frame_parity(
        SimpleNamespace(),
        rpu_path=rpu,
        hevc_path=hevc,
        frame_evidence=evidence,
        probe_rpu_frame_count=lambda *_a, **_k: 100,
    )
    assert "zeit" in temp.failure["reason"].lower()


def test_fast_hevc_probe_never_uses_count_frames(tmp_path):
    from dragontools.worker.dv_dynamic_metadata_service import DVDynamicMetadataService

    seen = []
    service = DVDynamicMetadataService(
        tools=SimpleNamespace(ffprobe="ffprobe", dovi_tool="dovi_tool"),
        temp_state=SimpleNamespace(),
        audio_mux_service=None,
        rpu_service=None,
        hdr10plus_service=None,
        generator_client=None,
        level5_editor=None,
        failure_recovery=None,
        log=lambda *_a, **_k: None,
        verbose_log=lambda *_a, **_k: None,
        assert_nonempty_file=lambda *_a, **_k: True,
    )

    class Runner:
        def run(self, cmd, **kwargs):
            seen.extend(cmd)
            return SimpleNamespace(returncode=0, stdout="nb_frames=N/A\n", stderr="")

    assert service.probe_hevc_frame_count(Runner(), tmp_path / "raw.hevc") is None
    assert "-count_frames" not in seen


def test_ffmpeg_progress_captures_actual_output_frame_count():
    from dragontools.worker.converter_progress_parser import read_progress

    class Proc:
        returncode = None
        stdout = iter([
            "frame=120\n",
            "out_time_ms=1000000\n",
            "frame=240\n",
            "progress=end\n",
        ])
        def poll(self):
            return None

    class Worker:
        abort_requested = False
        abort_type = None
        def wait_if_paused(self):
            return None
        def emit_file_progress(self, *_args):
            return None

    worker = Worker()
    read_progress(worker, Proc(), "source.mkv", 2000)
    assert worker._progress_frame_counts["source.mkv"] == 240


def test_generator_client_older_success_payload_infers_actual_analysis_count(tmp_path):
    import json
    from dragontools.worker.hdr10plus_generator_client import HDR10PlusGeneratorClient
    from dragontools.worker.tool_runner import ToolRunResult

    exe = tmp_path / "HDRPlusGenerator.exe"
    source = tmp_path / "source.hevc"
    output = tmp_path / "meta.json"
    exe.write_bytes(b"x")
    source.write_bytes(b"video")

    def fake_run(command, **kwargs):
        output.write_text('{"SceneInfo":[]}', encoding="utf-8")
        return ToolRunResult(command=list(command), returncode=0, stdout=json.dumps({"success": True, "frames": 321, "scenes": 2}))

    result = HDR10PlusGeneratorClient(str(exe), run_tool_fn=fake_run).analyze(source, output)
    assert result.success
    assert result.frames == 321
    assert result.frame_count_source == "analysis_actual"
    assert result.frame_count_reliability == "reliable"


def test_postprocess_gate_abort_does_not_consume_slot():
    gate = DVPostprocessGate(1)
    assert gate.acquire()
    assert gate.acquire(abort_requested=lambda: True) is False
    assert gate.active == 1
    gate.release()
    assert gate.active == 0


def test_dv_without_hdr10plus_reuses_encoder_frame_evidence(tmp_path):
    from dragontools.worker.dv_dynamic_metadata_service import DVDynamicMetadataService

    enc = tmp_path / "encoded.hevc"
    injected = tmp_path / "injected.hevc"
    rpu = tmp_path / "meta.rpu"
    verify = tmp_path / "verify.rpu"
    enc.write_bytes(b"encoded")
    rpu.write_bytes(b"rpu")
    evidence = FrameCountEvidence.reliable(
        240,
        source="ffmpeg_encode_progress",
        path=enc,
        stage="encode",
        temporal_mapping="preserved",
    )
    captured = {}

    class RpuService:
        def inject_rpu(self, _run, *, input_hevc, input_rpu, output_hevc):
            output_hevc.write_bytes(b"injected")
            return True

    state = SimpleNamespace(
        request=SimpleNamespace(generate_hdr10plus=False, requires_hdr10plus=False, preserve_dv_hdr10plus_combo=False),
        files=SimpleNamespace(enc_hevc=enc, injected=injected, rpu_verify=verify),
        rpu_to_use=rpu,
        encoded_frame_evidence=evidence,
        rpu_input_frame_evidence=None,
    )
    service = DVDynamicMetadataService(
        tools=SimpleNamespace(),
        temp_state=SimpleNamespace(record_failure=lambda **_kw: None),
        audio_mux_service=None,
        rpu_service=RpuService(),
        hdr10plus_service=None,
        generator_client=None,
        level5_editor=None,
        failure_recovery=None,
        log=lambda *_a, **_k: None,
        verbose_log=lambda *_a, **_k: None,
        assert_nonempty_file=lambda path, _label: Path(path).is_file() and Path(path).stat().st_size > 0,
    )

    def parity(_runner, *, frame_evidence=None, **_kwargs):
        captured["evidence"] = frame_evidence
        return True

    assert service.inject_dynamic_metadata(
        state,
        SimpleNamespace(adapter=lambda **_kw: (lambda *_a, **_k: 0)),
        validate_rpu_frame_parity=parity,
        verify_injected_rpu=lambda *_a, **_k: True,
    )
    assert captured["evidence"] is evidence
    assert state.rpu_input_frame_evidence is evidence


def test_hdr10plus_analysis_count_is_reused_after_metadata_injection(tmp_path):
    from dragontools.worker.dv_dynamic_metadata_service import DVDynamicMetadataService
    from dragontools.worker.hdr10plus_generator_client import HDR10PlusGeneratorResult

    enc = tmp_path / "encoded.hevc"
    hdr_json = tmp_path / "hdr.json"
    hdr_hevc = tmp_path / "hdr.hevc"
    enc.write_bytes(b"encoded")
    encoded = FrameCountEvidence.reliable(
        500,
        source="ffmpeg_encode_progress",
        path=enc,
        stage="encode",
        temporal_mapping="preserved",
    )

    class Generator:
        def analyze(self, input_path, output_path):
            Path(output_path).write_text('{"SceneInfo":[]}', encoding="utf-8")
            return HDR10PlusGeneratorResult(
                True, 0, frames=500, frame_count_source="analysis_actual", frame_count_reliability="reliable"
            )

    class HDRService:
        def inject_metadata(self, _run, *, input_hevc, metadata_json, output_hevc):
            output_hevc.write_bytes(b"hdr")
            return True

    state = SimpleNamespace(
        files=SimpleNamespace(enc_hevc=enc, hdr10plus_json=hdr_json, hdr10plus_hevc=hdr_hevc),
        encoded_frame_evidence=encoded,
        hdr10plus_frame_evidence=None,
        rpu_input_frame_evidence=None,
    )
    service = DVDynamicMetadataService(
        tools=SimpleNamespace(),
        temp_state=SimpleNamespace(record_failure=lambda **_kw: None),
        audio_mux_service=None,
        rpu_service=None,
        hdr10plus_service=HDRService(),
        generator_client=Generator(),
        level5_editor=None,
        failure_recovery=None,
        log=lambda *_a, **_k: None,
        verbose_log=lambda *_a, **_k: None,
        assert_nonempty_file=lambda path, _label: Path(path).is_file() and Path(path).stat().st_size > 0,
    )
    output = service._prepare_hdr10plus_bitstream(
        state,
        SimpleNamespace(adapter=lambda **_kw: (lambda *_a, **_k: 0)),
        generate=True,
    )
    assert output == hdr_hevc
    assert state.hdr10plus_frame_evidence.count == 500
    assert state.rpu_input_frame_evidence.count == 500
    assert state.rpu_input_frame_evidence.is_reliable_for(hdr_hevc)


def test_progress_activity_label_distinguishes_encode_and_postprocessing():
    from dragontools.gui.conversion_progress_presenter import ConversionProgressPresenter

    worker = SimpleNamespace(
        encode_active_count=lambda: 1,
        postprocessing_file_count=lambda: 3,
    )
    label = ConversionProgressPresenter._total_activity_label(None, 2, 6, worker)
    assert label == "Gesamt: 2/6 fertig · 1 Encode · 3 Nachbearbeitung"


def test_generator_builder_requires_python_312_and_release_smoke_uses_windows_qt():
    root = Path(__file__).resolve().parents[2]
    builder = (root / "dragon_hdr10plus_generator" / "build.bat").read_text(encoding="utf-8")
    workflow = (root / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert "sys.version_info >= (3, 12)" in builder
    assert '$env:QT_QPA_PLATFORM = "windows"' in workflow


def test_ffmpeg_progress_drains_buffer_after_process_exit_and_requires_progress_end():
    from dragontools.worker.converter_progress import ConverterProgressHelper
    from dragontools.worker.converter_progress_parser import read_progress

    class Proc:
        stdout = iter([
            "frame=100\n",
            "frame=200\n",
            "progress=end\n",
        ])

        def poll(self):
            # Regression: the process may already be reaped while stdout still
            # contains buffered final progress records.
            return 0

    class Worker:
        abort_requested = False
        abort_type = None

        def wait_if_paused(self):
            return None

        def emit_file_progress(self, *_args):
            return None

    worker = Worker()
    read_progress(worker, Proc(), "source.mkv", 2_000)
    helper = ConverterProgressHelper(worker)
    assert helper.take_output_frame_count("source.mkv", process_rc=0) == 200

    # A frame value without progress=end is only an intermediate observation
    # and must never become reliable encode evidence.
    worker2 = Worker()
    proc2 = type("Proc2", (), {"stdout": iter(["frame=333\n"]), "poll": lambda self: 0})()
    read_progress(worker2, proc2, "source2.mkv", 2_000)
    helper2 = ConverterProgressHelper(worker2)
    assert helper2.take_output_frame_count("source2.mkv", process_rc=0) is None
