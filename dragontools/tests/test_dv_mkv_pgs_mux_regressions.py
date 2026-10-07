from pathlib import Path
from types import SimpleNamespace
import json

import pytest

from dragontools.worker.dv_mkv_muxer import DVMKVMuxer
from dragontools.worker.dv_remux_muxers import DVRemuxMuxer
from dragontools.worker.dv_subtitle_mux_service import DVMuxSubtitleTrack
from dragontools.worker.dv_mkv_source_subtitles import resolve_subtitle_ids
from dragontools.worker.dv_command_runner import DVCommandRunner
from dragontools.worker.dv_runtime_models import DVTempState
from dragontools.worker.tool_runner import ToolRunResult


@pytest.mark.parametrize("remux", [False, True])
@pytest.mark.parametrize("rc", [0, 1, 2])
def test_direct_pgs_selects_only_actual_source_ids(tmp_path, remux, rc):
    video, source, output = [tmp_path / name for name in ("video.hevc", "source.mkv", "out.mkv")]
    video.write_bytes(b"video")
    source.write_bytes(b"source")
    tracks = [DVMuxSubtitleTrack(source, idx, "pgs", "deu", "Deutsch", forced, True)
              for idx, forced in ((3, False), (7, True))]
    calls = []
    logs = []

    def capture(command):
        calls.append(command)
        if "-select_streams" in command:
            return SimpleNamespace(returncode=0, stdout=json.dumps({"streams": [{"index": 3}, {"index": 7}]}), stderr="")
        if "-J" in command:
            return SimpleNamespace(returncode=0, stdout=json.dumps({"tracks": [
                {"type": "video", "id": 0}, {"type": "subtitles", "id": 9}, {"type": "subtitles", "id": 12},
            ]}), stderr="")
        output.write_bytes(b"mkv")
        return SimpleNamespace(returncode=rc, stdout="", stderr="warning" if rc == 1 else "")

    if remux:
        class Runner:
            def run_abortable_capture(self, command, **kwargs):
                result = capture(command)
                return result.returncode, result.stdout, result.stderr
        worker = SimpleNamespace(tools=SimpleNamespace(mkvmerge="mkvmerge", ffprobe="ffprobe"),
                                 log=lambda *args: logs.append(args))
        ok = DVRemuxMuxer(worker, Runner()).mux_mkv(str(video), [], str(output), tracks)
    else:
        def run(command, return_process=False, **kwargs):
            if return_process:
                assert kwargs["timeout"] == 60
                assert kwargs["label"] == "PGS-Quellenanalyse"
            result = capture(command)
            return result if return_process else result.returncode
        mux = DVMKVMuxer(mkvmerge_path="mkvmerge", audio_track_name=lambda _: "", log=lambda *args: logs.append(args))
        ok = mux.mux_final_output(run, output_path=str(output), injected_hevc=video, mux_tracks=[], subtitle_tracks=tracks)
    assert ok is (rc in (0, 1))
    assert len(calls) == 3  # One inventory pair per source, then final mux.
    cmd = calls[-1]
    assert [cmd[i+1] for i, value in enumerate(cmd) if value == "--subtitle-tracks"] == ["9", "12"]
    assert "9:no" in cmd and "12:yes" in cmd
    for flag in ("--no-video", "--no-audio", "--no-buttons", "--no-attachments", "--no-chapters", "--no-global-tags", "--no-track-tags"):
        assert cmd.count(flag) == 2
    if rc == 1:
        assert any(level == "warn" for _, level in logs)


@pytest.mark.parametrize("remux", [False, True])
def test_unresolved_pgs_fails_before_mux(tmp_path, remux):
    source = tmp_path / "source.mkv"
    source.write_bytes(b"source")
    track = DVMuxSubtitleTrack(source, 99, "pgs", "deu", "Deutsch", False, True)
    calls = []
    def capture(cmd):
        calls.append(cmd)
        data = {"streams": [{"index": 3}]} if "-select_streams" in cmd else {"tracks": [{"type": "subtitles", "id": 8}]}
        return SimpleNamespace(returncode=0, stdout=json.dumps(data), stderr="")
    if remux:
        class Runner:
            def run_abortable_capture(self, cmd, **kwargs):
                r = capture(cmd)
                return r.returncode, r.stdout, r.stderr
        worker = SimpleNamespace(tools=SimpleNamespace(mkvmerge="mkvmerge"), log=lambda *_: None)
        ok = DVRemuxMuxer(worker, Runner()).mux_mkv("video.hevc", [], str(tmp_path / "out.mkv"), [track])
    else:
        def run(cmd, **kwargs):
            return capture(cmd)
        ok = DVMKVMuxer(mkvmerge_path="mkvmerge", audio_track_name=lambda _: "").mux_final_output(
            run, output_path=str(tmp_path / "out.mkv"), injected_hevc=Path("video.hevc"), mux_tracks=[], subtitle_tracks=[track])
    assert not ok
    assert len(calls) == 2
    assert not (tmp_path / "out.mkv").exists()


@pytest.mark.parametrize("stdout,rc", [('invalid', 0), ('{}', 0), ('{}', 2), ('{"streams":[]}', 0)])
def test_invalid_source_analysis_is_rejected(stdout, rc):
    def capture(cmd):
        if "-J" in cmd:
            return SimpleNamespace(returncode=0, stdout='{"tracks":[{"type":"subtitles","id":2}]}')
        return SimpleNamespace(returncode=rc, stdout=stdout)
    with pytest.raises(ValueError):
        resolve_subtitle_ids(path="source.mkv", ffprobe="ffprobe", mkvmerge="mkvmerge", capture=capture)


def test_warning_does_not_poison_dv_failure_diagnostics(monkeypatch):
    state = DVTempState()
    logs = []
    monkeypatch.setattr("dragontools.worker.dv_command_runner.run_tool", lambda cmd, **kwargs:
                        ToolRunResult(command=cmd, returncode=1, stdout="Warning: test"))
    runner = DVCommandRunner(log=lambda *args: logs.append(args), verbose_log=lambda *_: None,
                             no_window_kwargs=lambda: {}, temp_state=state)
    assert runner.run(["mkvmerge.exe", "-o", "out.mkv"]) == 1
    assert state.failure_reason == "" and state.stderr == ""
    assert any("Warning: test" in message and level == "warn" for message, level in logs)
