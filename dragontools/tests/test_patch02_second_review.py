from __future__ import annotations

import json
import io
import os
import sys
import subprocess
import threading
import zipfile
from types import SimpleNamespace

import pytest


def test_windows_pid_probe_never_sends_a_signal(monkeypatch):
    if os.name != "nt":
        pytest.skip("native Windows process status")
    from dragontools.core import crash_guard

    calls = []
    monkeypatch.setattr(crash_guard, "os", SimpleNamespace(name="nt", kill=lambda *args: calls.append(args)))
    assert crash_guard._pid_is_running(os.getpid()) is True
    assert calls == []


@pytest.mark.parametrize("text", ["password=[REDACTED]", "Authorization: Basic abc", '"password": "a\\\"secret-tail"'])
def test_secret_redaction_is_complete_and_idempotent(text):
    from dragontools.core.diagnostic_redaction import redact_sensitive_text

    redacted = redact_sensitive_text(text)
    assert "secret-tail" not in redacted
    assert "abc" not in redacted
    assert redact_sensitive_text(redacted) == redacted


def test_analysis_timeout_stops_owned_child(tmp_path):
    from dragontools.core.process_runner import run_analysis_tool

    marker = tmp_path / "child_finished.txt"
    child_code = f"import time,pathlib; time.sleep(2); pathlib.Path({str(marker)!r}).write_text('orphan')"
    parent_code = f"import subprocess,sys,time; subprocess.Popen([sys.executable, '-c', {child_code!r}]); time.sleep(20)"
    with pytest.raises(RuntimeError, match="Timeout"):
        run_analysis_tool([sys.executable, "-c", parent_code], timeout=.5)
    # A timer provides a generous completion window without polling process IDs.
    threading.Event().wait(2.2)
    assert not marker.exists()


def test_logging_failure_does_not_prevent_owned_process_abort(monkeypatch):
    from dragontools.worker import process_control

    class Process:
        pid = 43210
        ended = False

        def poll(self):
            return 0 if self.ended else None

        def wait(self, timeout=None):
            self.ended = True
            return 0

    proc = Process()
    worker = SimpleNamespace(_current_process=proc)
    monkeypatch.setattr(process_control, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(process_control, "_taskkill_tree", lambda *_a, **_k: True)

    def broken_log(*_args):
        raise RuntimeError("GUI signal was deleted")

    assert process_control.terminate_process_tree(worker, threading.Lock(), log=broken_log)
    assert proc.ended
    assert worker._current_process is None


def test_log_internal_typeerror_is_not_retried():
    from dragontools.worker.process_control import _log_process_control

    calls = []

    def broken_log(*args):
        calls.append(args)
        raise TypeError("inside callback")

    _log_process_control(broken_log, "message")
    assert len(calls) == 1


def test_diagnostic_all_members_redact_known_secrets_and_private_roots(tmp_path, monkeypatch):
    from dragontools.core import diagnostic_package as module
    from dragontools.core.settings import SET_KEY_METADATA_TMDB_API_KEY

    secret = "known-secret-20261005"
    private = tmp_path / "Private_User"
    private.mkdir()
    settings = SimpleNamespace(
        allKeys=lambda: [SET_KEY_METADATA_TMDB_API_KEY, "ordinary/value", "paths/temp"],
        value=lambda key, default=None, **_kw: {
            SET_KEY_METADATA_TMDB_API_KEY: secret,
            "ordinary/value": secret,
            "paths/temp": str(private / "temp"),
        }.get(key, default),
    )
    log = private / "Logging" / "run.txt"
    log.parent.mkdir()
    log.write_text(f"source {private / 'film.mkv'}\n", encoding="utf-8")
    monkeypatch.setattr(module, "log_base_from_settings", lambda _s: private)
    monkeypatch.setattr(module, "verbose_log_dir_from_settings", lambda _s: private / "VerboseLog")
    monkeypatch.setattr(module, "_tool_diagnostics_text", lambda: f"tool echoed {secret} at {private}\n")
    monkeypatch.setattr(module, "_extended_systemtest_text", lambda: f"password=another-secret {private}\n")
    result = module.create_diagnostic_package(tmp_path / "diag.zip", settings=settings, documents_dir=private)
    with zipfile.ZipFile(result) as archive:
        combined = "\n".join(archive.read(name).decode("utf-8") for name in archive.namelist())
        json.loads(archive.read("settings.json"))
    assert secret not in combined
    assert "another-secret" not in combined
    assert "Private_User" not in combined
    assert "film.mkv" in combined


def test_partial_lines_count_as_live_activity():
    from dragontools.worker.tool_runner import run_tool

    result = run_tool(
        [sys.executable, "-u", "-c", "import sys,time\nfor i in range(12):\n sys.stdout.write('x'); sys.stdout.flush(); time.sleep(.15)"],
        timeout_s=.8,
        timeout_mode="inactivity",
    )
    assert result.ok, result
    assert result.stdout == "x" * 12
    assert not result.timed_out


def test_binary_output_over_limit_is_never_reported_complete(monkeypatch):
    from dragontools.worker import tool_runner

    monkeypatch.setattr(tool_runner, "MAX_BINARY_OUTPUT_BYTES", 32, raising=False)
    result = tool_runner.run_tool_bytes([sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'x' * 128)"])
    assert result.returncode == 75
    assert len(result.stdout) <= 32


def test_failed_output_reader_cannot_report_success(monkeypatch):
    from dragontools.worker import tool_runner

    class BrokenStream:
        def readline(self, *_args):
            raise OSError("broken output pipe")

        def close(self):
            return None

    proc = SimpleNamespace(pid=12345, poll=lambda: 0, stdout=BrokenStream(), stderr=io.StringIO())
    monkeypatch.setattr(tool_runner.subprocess, "Popen", lambda *_a, **_kw: proc)
    result = tool_runner.run_tool(["example-tool"])
    assert result.returncode == 75
    assert "broken output pipe" in result.stderr


def test_unexpected_runtime_error_propagates_and_stops_owned_child(monkeypatch):
    from dragontools.worker import tool_runner

    processes = []
    popen = subprocess.Popen

    def capture(*args, **kwargs):
        proc = popen(*args, **kwargs)
        processes.append(proc)
        return proc

    def fail_pause(_self):
        raise RuntimeError("unexpected programming error")

    monkeypatch.setattr(tool_runner.subprocess, "Popen", capture)
    monkeypatch.setattr(tool_runner.ProcessLifecycle, "handle_pause", fail_pause)
    try:
        with pytest.raises(RuntimeError, match="unexpected programming error"):
            tool_runner.run_tool([sys.executable, "-c", "import time; time.sleep(20)"])
        assert processes[0].poll() is not None
    finally:
        for proc in processes:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)


def test_process_tree_close_does_not_stop_a_sibling(tmp_path):
    from dragontools.worker.tool_runner import run_tool

    orphan_marker = tmp_path / "orphan.txt"
    sibling_marker = tmp_path / "sibling.txt"
    child_code = f"import time,pathlib; time.sleep(1); pathlib.Path({str(orphan_marker)!r}).write_text('bad')"
    parent_code = f"import subprocess,sys; subprocess.Popen([sys.executable,'-c',{child_code!r}]); print('parent-ok')"
    sibling = subprocess.Popen([sys.executable, "-c", f"import time,pathlib; time.sleep(1); pathlib.Path({str(sibling_marker)!r}).write_text('ok')"])
    try:
        result = run_tool([sys.executable, "-c", parent_code], timeout_s=5)
        assert result.ok
        assert "parent-ok" in result.stdout
        sibling.wait(timeout=5)
        assert sibling_marker.read_text() == "ok"
        assert not orphan_marker.exists()
    finally:
        if sibling.poll() is None:
            sibling.kill()
            sibling.wait(timeout=5)


@pytest.mark.parametrize("failure", ["hardlink", "nested_link"])
def test_diagnostic_archive_preserves_ownership_boundaries(tmp_path, monkeypatch, failure):
    from dragontools.core import diagnostic_package as module

    settings = SimpleNamespace(allKeys=lambda: [], value=lambda _key, default=None, **_kw: default)
    log_dir = tmp_path / "Logging" / "linked"
    log_dir.mkdir(parents=True)
    (log_dir / "private.txt").write_text("unrelated-private-content", encoding="utf-8")
    victim = tmp_path / "victim.bin"
    victim.write_bytes(b"keep-existing-file")
    target = tmp_path / "diag.zip"
    if failure == "hardlink":
        try:
            target.hardlink_to(victim)
        except OSError:
            pytest.skip("hardlinks unavailable")
    else:
        old_check = module._is_link_or_junction
        monkeypatch.setattr(module, "_is_link_or_junction", lambda path: path == log_dir or old_check(path))
    monkeypatch.setattr(module, "log_base_from_settings", lambda _s: tmp_path)
    monkeypatch.setattr(module, "verbose_log_dir_from_settings", lambda _s: tmp_path / "VerboseLog")
    monkeypatch.setattr(module, "_tool_diagnostics_text", lambda: "ok")
    monkeypatch.setattr(module, "_extended_systemtest_text", lambda: "ok")
    module.create_diagnostic_package(target, settings=settings, documents_dir=tmp_path)
    assert victim.read_bytes() == b"keep-existing-file"
    if failure == "nested_link":
        with zipfile.ZipFile(target) as archive:
            assert all(b"unrelated-private-content" not in archive.read(name) for name in archive.namelist())


def test_worker_logger_factory_survives_unwritable_root(tmp_path, monkeypatch):
    from dragontools.core import logger

    occupied = tmp_path / "occupied"
    occupied.write_text("not a directory")
    monkeypatch.setattr(logger, "log_settings_from_qsettings", lambda _settings: (True, occupied))
    result = logger.create_worker_logger(settings=object())
    result.info("conversion can continue")
    assert result.log_file is None
    assert result.has_logging_failures


def test_disabled_verbose_factory_does_not_enable_fallback(monkeypatch):
    from dragontools.core import logger_verbose as module

    calls = []
    monkeypatch.setattr(module, "settings_bool", lambda *_args: False)
    monkeypatch.setattr(module, "VerboseLogger", lambda **kw: SimpleNamespace(enabled=kw["enabled"]))

    def fail_path(_settings):
        calls.append(True)
        raise OSError("unwritable directory")

    monkeypatch.setattr(module, "verbose_log_dir_from_settings", fail_path)
    result = module.create_verbose_logger(settings=object())
    assert result.enabled is False
    assert calls == []


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_analysis_output_flood_stops_at_limit(monkeypatch, stream):
    from dragontools.core import analysis_process
    from dragontools.core.process_runner import run_analysis_tool

    monkeypatch.setattr(analysis_process, "MAX_ANALYSIS_OUTPUT_BYTES", 32)
    with pytest.raises(RuntimeError, match="Speichergrenze"):
        run_analysis_tool([sys.executable, "-u", "-c", f"import sys,time; sys.{stream}.write('x'*128); sys.{stream}.flush(); time.sleep(20)"], timeout=.8)


def test_binary_stderr_flood_stops_at_limit(monkeypatch):
    from dragontools.worker import tool_runner

    monkeypatch.setattr(tool_runner, "MAX_BINARY_OUTPUT_BYTES", 32)
    result = tool_runner.run_tool_bytes([sys.executable, "-u", "-c", "import sys,time; sys.stderr.write('x'*128); sys.stderr.flush(); time.sleep(20)"], timeout_s=.8)
    assert result.returncode == 75
    assert not result.timed_out


def test_completed_binary_tool_cannot_hide_stderr_overflow(monkeypatch):
    from dragontools.worker import tool_runner

    def completed_tool(_command, **kwargs):
        kwargs["stderr"].write(b"x" * 128)
        kwargs["stderr"].flush()
        return SimpleNamespace(pid=12345, poll=lambda: 0)

    monkeypatch.setattr(tool_runner, "MAX_BINARY_OUTPUT_BYTES", 32)
    monkeypatch.setattr(tool_runner, "spawn_owned_process", completed_tool)
    result = tool_runner.run_tool_bytes(["fake-tool"])
    assert result.returncode == 75


@pytest.mark.parametrize("text", [r"source D:\Private_Movies\film.mkv", json.dumps({"source_root": r"D:\Private_Movies"}), r"source \\server\Private_Movies\film.mkv", "source /home/server/Private_Movies/film.mkv", "source /var/data/Private_Movies/film.mkv"])
def test_support_privacy_covers_paths_outside_configured_roots(text):
    from dragontools.core.diagnostic_privacy import DiagnosticSanitizer

    cleaned = DiagnosticSanitizer()(text)
    assert "Private_Movies" not in cleaned
    assert "server" not in cleaned
    if text.startswith("{"):
        json.loads(cleaned)


@pytest.mark.parametrize("secret", ['key"x\\more', 'credentialÄ😃'])
def test_known_secret_redaction_handles_json_escaping(secret):
    from dragontools.core.diagnostic_redaction import redact_sensitive_text

    serialized = json.dumps({"echo": secret})
    cleaned = redact_sensitive_text(serialized, secret_values=[secret])
    assert json.loads(cleaned)["echo"] == "[REDACTED]"


def test_two_app_instances_keep_independent_crash_markers(tmp_path):
    from pathlib import Path
    from dragontools.core.owned_process import spawn_owned_process, close_owned_job

    project = Path(__file__).resolve().parents[2]
    prefix = f"import sys; sys.path.insert(0, {str(project)!r}); from pathlib import Path; from dragontools.core import crash_guard as g; g.make_log_dir=lambda _root: Path({str(tmp_path)!r}); g._pid_is_running=lambda _pid: True; g.install_crash_guard('test'); "
    first = spawn_owned_process([sys.executable, "-u", "-c", prefix + "import os,time; print(os.getpid(),flush=True); time.sleep(3)"], stdout=subprocess.PIPE)
    try:
        first_pid = int(first.stdout.readline().strip())
        second = subprocess.run([sys.executable, "-c", prefix + "g.clear_activity()"], timeout=10, capture_output=True)
        assert second.returncode == 0
        markers = list(tmp_path.rglob("crash_state*.json"))
        assert any(json.loads(path.read_text(encoding="utf-8")).get("pid") == first_pid for path in markers)
    finally:
        close_owned_job(first)
        if first.poll() is None:
            first.kill()
        first.wait(timeout=5)
        first.stdout.close()


@pytest.mark.parametrize("payload", ["[]", "null"])
def test_invalid_crash_state_shape_is_reported_and_ignored(tmp_path, monkeypatch, payload):
    from dragontools.core import crash_guard

    state = tmp_path / "crash_state.json"
    state.write_text(payload)
    monkeypatch.setattr(crash_guard, "_state_file", state)
    assert crash_guard._read_state() == {}


def test_named_active_crash_markers_are_neither_cleaned_nor_exported(tmp_path):
    from dragontools.core.diagnostic_package import _selected_log_files
    from dragontools.core.log_cleanup import cleanup_logs

    state = tmp_path / "Logging" / "CrashReports" / "crash_state_12345.json"
    state.parent.mkdir(parents=True)
    state.write_text('{"active":true}')
    ordinary = state.parent / "report.txt"
    ordinary.write_text("report")
    assert _selected_log_files(tmp_path, max_logs_per_category=10) == [ordinary]
    cleanup_logs(tmp_path)
    assert state.exists()
    assert not ordinary.exists()


@pytest.mark.parametrize("duration", [10.0, 10.25])
def test_frame_windows_preserve_long_analysis_under_output_limit(monkeypatch, duration):
    import math
    from dragontools.core import audio_video_frame_analysis as module
    from dragontools.core.audio_video_match_models import AudioVideoMatcherSettings

    monkeypatch.setattr(module, "FRAME_WINDOW_BYTE_BUDGET", 64, raising=False)
    monkeypatch.setattr(module, "_signature_from_gray_frame", lambda _frame, _w, _h, time_s: SimpleNamespace(time_s=time_s))
    calls = []

    def bounded_tool(cmd, _timeout):
        seconds = float(cmd[cmd.index("-t") + 1])
        frames = math.ceil(seconds * 2)
        calls.append((float(cmd[cmd.index("-ss") + 1]), seconds))
        if frames * 16 > 64:
            raise RuntimeError("output limit")
        return b"x" * (frames * 16)

    extractor = module.FrameExtractor("ffmpeg", settings=AudioVideoMatcherSettings(analysis_width=4, analysis_height=4), run_bytes=bounded_tool)
    signatures = extractor.extract_window_signatures("movie.mkv", 3, duration, fps=2)
    assert len(signatures) == math.ceil(duration * 2)
    assert [signature.time_s for signature in signatures] == [3 + index / 2 for index in range(len(signatures))]
    assert len(calls) > 1


def test_headless_frame_reader_preserves_exact_binary_bytes():
    from dragontools.core.audio_video_frame_analysis import _default_run_bytes

    payload = b"\x00\xff\r\nABC"
    assert _default_run_bytes([sys.executable, "-c", f"import sys; sys.stdout.buffer.write({payload!r})"], 5) == payload


def test_binary_spool_failure_is_a_structured_result(monkeypatch):
    from dragontools.worker import tool_runner

    def fail_capture():
        raise OSError("temporary disk full")

    monkeypatch.setattr(tool_runner, "BinaryOutputCapture", fail_capture)
    result = tool_runner.run_tool_bytes(["tool"])
    assert result.returncode == 126
    assert b"temporary disk full" in result.stderr


@pytest.mark.parametrize("mode", ["run", "run_capture", "run_progress"])
def test_converter_adapter_timeout_stops_owned_children(tmp_path, mode):
    from dragontools.worker.converter_process_executor import ConverterProcessExecutor

    marker = tmp_path / "converter-child.txt"
    python = getattr(sys, "_base_executable", sys.executable)
    child = f"import time,pathlib; time.sleep(1); pathlib.Path({str(marker)!r}).write_text('orphan')"
    code = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(3)"
    worker = SimpleNamespace(_lock=threading.Lock(), _current_process=None, _paused=False, abort_requested=False, abort_type=None, log=lambda *_args: None)
    executor = ConverterProcessExecutor(worker)
    command = [python, "-c", code]
    if mode == "run_progress":
        def read_progress(proc, *_args):
            for _line in proc.stdout:
                pass
        rc = executor.run_progress(command, "input.mkv", 1000, timeout_s=.3, label="owned", probe_frames=lambda _path: None, read_progress=read_progress)
    else:
        result = getattr(executor, mode)(command, timeout_s=.3)
        rc = result[0] if mode == "run_capture" else result
    assert rc == 124
    threading.Event().wait(1.2)
    assert not marker.exists()


def test_converter_progress_reader_error_is_not_hidden():
    from dragontools.worker.converter_process_executor import ConverterProcessExecutor

    worker = SimpleNamespace(_lock=threading.Lock(), _current_process=None, _paused=False, abort_requested=False, abort_type=None, log=lambda *_args: None)

    def broken_progress(*_args):
        raise RuntimeError("progress reader programming error")

    with pytest.raises(RuntimeError, match="progress reader programming error"):
        ConverterProcessExecutor(worker).run_progress([sys.executable, "-c", "import time; time.sleep(.1)"], "input.mkv", 1000, timeout_s=5, label="reader", probe_frames=lambda _path: None, read_progress=broken_progress)
