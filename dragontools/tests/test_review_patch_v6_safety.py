# -*- coding: utf-8 -*-
from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace


def test_process_lifecycle_register_does_not_reenter_converter_process_lock(monkeypatch):
    from dragontools.worker import tool_process_lifecycle as lifecycle_module
    from dragontools.worker.tool_process_lifecycle import ProcessLifecycle

    monkeypatch.setattr(lifecycle_module, "mark_activity", lambda *args, **kwargs: None)
    state = SimpleNamespace(
        process_lock=threading.Lock(),
        current_process=None,
        abort_requested=False,
        abort_type=None,
        paused=False,
    )
    worker = SimpleNamespace(_control_state=state)
    proc = SimpleNamespace(pid=12345)
    lifecycle = ProcessLifecycle(["tool"], "Test", 10, worker=worker)

    thread = threading.Thread(target=lambda: lifecycle.register(proc), daemon=True)
    thread.start()
    thread.join(0.5)

    assert not thread.is_alive(), "ProcessLifecycle.register() deadlockt am process_lock"
    assert state.current_process is proc

    finish_thread = threading.Thread(target=lambda: lifecycle.finish(0), daemon=True)
    finish_thread.start()
    finish_thread.join(0.5)
    assert not finish_thread.is_alive(), "ProcessLifecycle.finish() deadlockt am process_lock"
    assert state.current_process is None


def test_terminate_process_tree_uses_control_state_without_property_reentry():
    from dragontools.worker.process_control import terminate_process_tree

    class DoneProc:
        pid = 123
        def poll(self):
            return 0

    proc = DoneProc()
    state = SimpleNamespace(process_lock=threading.Lock(), current_process=proc)
    worker = SimpleNamespace(_control_state=state)
    thread = threading.Thread(
        target=lambda: terminate_process_tree(worker, state.process_lock, log=lambda *_: None),
        daemon=True,
    )
    thread.start()
    thread.join(0.5)
    assert not thread.is_alive(), "terminate_process_tree() deadlockt am Control-State-Lock"
    assert state.current_process is None


def test_sql_read_only_classifier_handles_cte_comments_explain_and_pragmas():
    from dragontools.core.media_library_db import sql_is_read_only

    assert sql_is_read_only("SELECT 1")
    assert sql_is_read_only("/* Diagnose */ SELECT 1")
    assert sql_is_read_only("-- Diagnose\nWITH x AS (SELECT 1) SELECT * FROM x")
    assert sql_is_read_only("VALUES (1), (2)")
    assert sql_is_read_only("EXPLAIN QUERY PLAN SELECT * FROM media_items")
    assert sql_is_read_only("PRAGMA table_info(media_items)")

    assert not sql_is_read_only("WITH x AS (SELECT 1) UPDATE media_items SET active=0")
    assert not sql_is_read_only("PRAGMA foreign_keys=OFF")
    assert not sql_is_read_only("SELECT 1; DELETE FROM media_items")


def test_mp4_remux_verification_failure_blocks_original_replace(tmp_path):
    from dragontools.worker.mp4_remux_file_service import MP4RemuxFileService
    from dragontools.worker.mp4_remux_plan import MP4RemuxPlan

    source = tmp_path / "Film.mp4"
    staging = tmp_path / "Film.__mp4_remux_tmp__.mp4"
    source.write_bytes(b"ORIGINAL")
    plan = MP4RemuxPlan(
        source=source,
        destination=source,
        staging=staging,
        command=("ffmpeg", str(staging)),
        duration_s=60.0,
        audio_plan=(),
        expected_audio_tracks=0,
        expected_subtitle_tracks=0,
    )

    class Planner:
        @staticmethod
        def build(*_args, **_kwargs):
            return plan
        @staticmethod
        def video_compatibility(_media):
            return True, "h264"

    class Logger:
        def file_start(self, *args, **kwargs): pass
        def file_done(self, *args, **kwargs): pass

    class Verifier:
        @staticmethod
        def verify(**_kwargs):
            return SimpleNamespace(ok=False, messages=("ffprobe-Prüfung fehlgeschlagen",))

    def run_ffmpeg(cmd, *_args):
        Path(cmd[-1]).write_bytes(b"BROKEN")
        return 0

    results = []
    service = MP4RemuxFileService(
        planner=Planner(),
        logger=Logger(),
        log=lambda *_args: None,
        run_ffmpeg=run_ffmpeg,
        export_sidecars=lambda *a, **k: None,
        commit_sidecars=lambda *a, **k: None,
        cleanup_sidecars=lambda *_args: None,
        abort_requested=lambda: False,
        emit_file_result=lambda *args: results.append(args),
        emit_file_progress=lambda *_args: None,
        export_subtitles=False,
        ignore_subtitles=True,
        output_verifier=Verifier(),
    )
    media = SimpleNamespace(analysis_warnings=[], analysis_source="test")
    ok = service.remux(str(source), str(source), media, current_index=1, total_files=1, user_abort_error=RuntimeError)

    assert ok is False
    assert source.read_bytes() == b"ORIGINAL"
    assert not staging.exists()
    assert results and results[-1][1] is False


def test_mp4_and_merge_verifiers_enforce_expected_track_counts():
    from dragontools.worker.mp4_remux_output_verifier import MP4RemuxOutputVerifier
    from dragontools.worker.merge_output_verifier import MergeOutputVerifier
    from dragontools.worker.workflow_engine import WorkflowVerifyResult

    base = WorkflowVerifyResult(
        exists=True, size_ok=True, container_ok=True, probe_ok=True, video_ok=True,
        audio_ok=True, subtitle_ok=True, contract_ok=True, metadata_ok=True,
        duration_ok=True, audio_stream_count=1, subtitle_stream_count=0, messages=[],
    )
    mp4 = MP4RemuxOutputVerifier(ffprobe_path="ffprobe")
    mp4._verifier = SimpleNamespace(verify=lambda *a, **k: base)
    assert not mp4.verify(output_path="x.mp4", expected_duration_ms=1000, expected_audio_tracks=2, expected_subtitle_tracks=0).ok

    merge = MergeOutputVerifier(ffprobe_path="ffprobe")
    merge._verifier = SimpleNamespace(verify=lambda *a, **k: base)
    assert not merge.verify(output_path="x.mkv", expected_duration_ms=1000, expected_audio_tracks=1, expected_subtitle_tracks=1).ok
