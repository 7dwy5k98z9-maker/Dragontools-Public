from __future__ import annotations

import ast
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace


def test_output_size_policy_rejects_missing_output(tmp_path):
    from dragontools.worker.output_size_policy import validate_output_size_policy

    source = tmp_path / "source.mkv"
    source.write_bytes(b"source")
    ok, preserved = validate_output_size_policy(source, tmp_path / "missing.mkv", settings={})
    assert ok is False
    assert preserved is None


def test_postprocess_error_is_reported_without_failing_successful_video():
    from dragontools.worker.postprocess_async import AsyncPostProcessCoordinator
    from dragontools.worker.postprocess_models import PostProcessRunResult

    class ResultService:
        def __init__(self):
            self.results = []
            self.progress = []
        def emit_file_progress(self, path, pct):
            self.progress.append((path, pct))
        def emit_file_result(self, input_path, output_path, status):
            self.results.append((input_path, output_path, status))

    coordinator = object.__new__(AsyncPostProcessCoordinator)
    coordinator.log = lambda *_args, **_kwargs: None
    future = Future()
    future.set_result(PostProcessRunResult([], [{"kind": "trickplay", "status": "error", "path": "", "message": "boom"}]))
    result_service = ResultService()
    postprocess_outputs = {}
    coordinator._complete(
        future,
        input_path="in.mkv",
        output_path="out.mkv",
        existing_sidecars=[],
        sidecar_outputs={},
        postprocess_outputs=postprocess_outputs,
        result_service=result_service,
    )
    assert result_service.progress == [("in.mkv", 100)]
    assert result_service.results == [("in.mkv", "out.mkv", "✅")]
    assert postprocess_outputs["in.mkv"][0]["status"] == "error"


def test_audio_mux_verifier_requires_expected_audio_count(monkeypatch):
    import dragontools.worker.audio_mux_output_verifier as module

    fake = SimpleNamespace(ok=True, audio_stream_count=1, messages=[])
    monkeypatch.setattr(module.OutputVerifier, "verify", lambda self, *a, **k: fake)
    verifier = module.AudioMuxOutputVerifier(ffprobe_path="ffprobe")
    result = verifier.verify(output_path="out.mkv", expected_duration_ms=1000, expected_audio_tracks=2)
    assert result.ok is False
    assert any("Audiospur-Anzahl" in message for message in result.messages)


def test_dv_remux_verifier_requires_actual_dolby_vision(monkeypatch):
    import dragontools.worker.dv_remux_output_verifier as module

    monkeypatch.setattr(module.OutputVerifier, "verify", lambda self, *a, **k: SimpleNamespace(ok=True, messages=[]))
    monkeypatch.setattr(
        module,
        "inspect_dynamic_hdr_with_mediainfo",
        lambda *a, **k: SimpleNamespace(conclusive=True, dolby_vision=False, warnings=()),
    )
    tools = SimpleNamespace(ffprobe="ffprobe")
    result = module.DVRemuxOutputVerifier(tools=tools).verify(
        output_path="out.mkv", container="mkv", expected_duration_ms=1000, source_has_audio=True
    )
    assert result.ok is False
    assert any("Dolby Vision" in message for message in result.messages)


def test_qthread_workers_do_not_shadow_native_finished_signal():
    root = Path(__file__).resolve().parents[1] / "worker"
    filenames = [
        "converter_thread.py", "audio_video_match_thread.py", "dv_remux_thread.py", "iso_thread.py",
        "audio_mux_thread.py", "quality_test_thread.py", "quality_compare_thread.py",
        "mp4_remux_thread.py", "merge_thread.py",
    ]
    for filename in filenames:
        tree = ast.parse((root / filename).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                assert not any(isinstance(target, ast.Name) and target.id == "finished" for target in targets), filename
        assert ".finished.emit(" not in (root / filename).read_text(encoding="utf-8"), filename


def test_move_thread_uses_distinct_result_signal():
    source = (Path(__file__).resolve().parents[1] / "worker" / "move_thread.py").read_text(encoding="utf-8")
    assert "batch_finished = pyqtSignal(bool, bool)" in source
    assert "self.batch_finished.emit(" in source
    assert "    finished = pyqtSignal(bool, bool)" not in source


def test_dv_after_file_abort_only_stops_outer_loop():
    source = (Path(__file__).resolve().parents[1] / "worker" / "dv_remux_job.py").read_text(encoding="utf-8")
    assert 'getattr(self.worker, "abort_type", None) == "sofort"' in source
    assert "abort_check=self._abort_current_file" in source


def test_dv_progress_uses_dynamic_queue_total():
    source = (Path(__file__).resolve().parents[1] / "worker" / "dv_remux_thread.py").read_text(encoding="utf-8")
    assert "total_after_processed(processed_count)" in source
    assert "min(100" in source
