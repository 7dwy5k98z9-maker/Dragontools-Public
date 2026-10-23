"""Disputed duration gates: independent confirmations and genuine truncations."""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
import json

import pytest

from dragontools.worker.duration_confirmation import (
    DurationConfirmationService, DurationVote, compare_durations, confirm_disputed_duration,
)
from dragontools.worker.duration_confirmation_sources import (
    DurationConfirmationSources, DurationSample, read_mkv_timestamps,
)
from dragontools.worker.media_contract_types import ExpectedAudioTrack, ExpectedMediaContract
from dragontools.worker.tool_runner import ToolRunResult
from dragontools.worker.workflow_engine import WorkflowVerifyResult
from dragontools.worker.workflow_verification_service import WorkflowVerificationService


def _result(**overrides):
    values = dict(exists=True, size_ok=True, container_ok=True, probe_ok=True,
                  video_ok=True, audio_ok=True, duration_ok=False, duration_s=2510.162,
                  messages=["Ausgabedauer ist nicht plausibel."])
    values.update(overrides)
    return WorkflowVerifyResult(**values)


def _contract(duration=2510.08):
    return ExpectedMediaContract("mkv", "hevc", 1,
                                 (ExpectedAudioTrack("ac3", 6, duration_s=duration),), ())


@pytest.fixture
def files(tmp_path):
    source, output = tmp_path / "source.mkv", tmp_path / "output.mkv"
    source.write_bytes(b"s" * 4096)
    output.write_bytes(b"o" * 4096)
    return source, output


def _service(files, samples):
    runtime = SimpleNamespace(worker=None, mkvmerge_path="mkvmerge", log=Mock())
    service = DurationConfirmationService(runtime)
    for name, value in samples.items():
        setattr(service.sources, name, Mock(side_effect=value if isinstance(value, Exception) else list(value)))
    return service


def _confirm(service, files, contract=None):
    return service.confirm(source_path=str(files[0]), output_path=str(files[1]), expected_contract=contract)


def test_stargate_mediainfo_estimate_does_not_veto_actual_unchanged_video(files):
    source = DurationSample(2494.6, 2510.082, (2510.08, 2510.08), True, 62365, .04)
    output = DurationSample(2494.6, 2510.162, (2510.08,), True, 62365, .04)
    mi_source = DurationSample(2510.08, 2510.082, (2510.08, 2510.08))
    mi_output = replace(output, measured=False, count=None)
    service = _service(files, {"ffprobe": (source, output), "mediainfo": (mi_source, mi_output),
                               "mkvtoolnix": (source, output)})
    votes = _confirm(service, files, _contract())
    assert [vote.accepted for vote in votes] == [True, False, True]


@pytest.mark.parametrize("winner", ["ffprobe", "mediainfo", "mkvtoolnix"])
def test_one_independent_confirmation_is_enough(files, winner):
    source = DurationSample(100, 100)
    output = DurationSample(100.2, 100.2)
    wrong = DurationSample(95, 95)
    service = _service(files, {name: ((source, output) if name == winner else (source, wrong))
                              for name in ("ffprobe", "mediainfo", "mkvtoolnix")})
    votes = _confirm(service, files)
    assert sum(vote.accepted for vote in votes) == 1
    assert next(vote for vote in votes if vote.accepted).tool == {
        "ffprobe": "ffprobe/FFmpeg", "mediainfo": "MediaInfo", "mkvtoolnix": "MKVToolNix",
    }[winner]


def test_all_tools_reject_real_truncation(files):
    source, output = DurationSample(100, 100), DurationSample(95, 95)
    service = _service(files, {name: (source, output) for name in ("ffprobe", "mediainfo", "mkvtoolnix")})
    assert not any(vote.accepted for vote in _confirm(service, files))


def test_stale_metadata_cannot_hide_measured_truncation(files):
    source = DurationSample(100, 100, measured=True, count=2500, frame_s=.04)
    output = DurationSample(95, 100, measured=True, count=2375, frame_s=.04)
    stale = DurationSample(100, 100)
    service = _service(files, {"ffprobe": (source, output), "mediainfo": (stale, stale),
                               "mkvtoolnix": (source, output)})
    votes = _confirm(service, files)
    assert not any(vote.accepted for vote in votes)
    assert "Metadaten widersprechen" in votes[1].detail


@pytest.mark.parametrize("delta,accepted", [(0.04, True), (0.8, True), (1.0, True), (1.001, False), (5, False)])
def test_tolerance_is_one_second_not_a_percentage(delta, accepted):
    source = DurationSample(3600, 3600)
    output = DurationSample(3600 - delta, 3600 - delta)
    assert (compare_durations(source, output, None) == "") is accepted


def test_packet_loss_with_preserved_last_timestamp_is_rejected():
    source = DurationSample(100, 100, measured=True, count=2500, frame_s=.04)
    output = DurationSample(100, 100, measured=True, count=2400, frame_s=.04)
    assert "anzahl" in compare_durations(source, output, None)


def test_equal_video_cannot_hide_corrupt_container():
    source = DurationSample(100, 100)
    output = DurationSample(100, 4295067.296)
    assert "Containerdauer" in compare_durations(source, output, None)


def test_audio_tail_is_allowed_but_truncated_selected_audio_is_rejected():
    source = DurationSample(100, 115, (115, 120))
    good = DurationSample(100, 115, (115,))
    assert compare_durations(source, good, _contract(115)) == ""
    truncated = DurationSample(100, 115, (110,))
    assert "Audiospur" in compare_durations(source, truncated, _contract(115))


def test_missing_tools_do_not_count_as_acceptance(files):
    service = _service(files, {name: RuntimeError("not available")
                              for name in ("ffprobe", "mediainfo", "mkvtoolnix")})
    votes = _confirm(service, files)
    assert len(votes) == 3 and not any(vote.accepted for vote in votes)


def test_one_available_tool_can_confirm_when_other_tools_are_missing(files):
    sample = DurationSample(100, 100)
    service = _service(files, {"ffprobe": (sample, sample), "mediainfo": RuntimeError("missing"),
                               "mkvtoolnix": RuntimeError("missing")})
    assert [vote.accepted for vote in _confirm(service, files)] == [True, False, False]


def test_changed_file_during_crosscheck_cannot_be_accepted(files):
    sample = DurationSample(100, 100)
    service = _service(files, {name: (sample, sample) for name in ("ffprobe", "mediainfo", "mkvtoolnix")})
    def change(_):
        files[1].write_bytes(b"changed while reading")
        return sample
    service.sources.mkvtoolnix.side_effect = change
    assert not any(vote.accepted for vote in _confirm(service, files))


def test_immediate_abort_prevents_crosscheck(files):
    sample = DurationSample(100, 100)
    service = _service(files, {name: (sample, sample) for name in ("ffprobe", "mediainfo", "mkvtoolnix")})
    service.runtime.worker = SimpleNamespace(abort_requested=True, abort_type="sofort")
    with pytest.raises(RuntimeError, match="abgebrochen"):
        _confirm(service, files)
    service.sources.ffprobe.assert_not_called()


@pytest.mark.parametrize("flag", ["exists", "size_ok", "probe_ok", "container_ok", "video_ok",
                                  "audio_ok", "subtitle_ok", "contract_ok", "metadata_ok"])
def test_confirmation_cannot_override_other_failures(files, flag):
    repair = SimpleNamespace(confirm_duration=Mock(return_value=(DurationVote("MediaInfo", True, "OK"),)))
    ctx = SimpleNamespace(input_path=str(files[0]), output_path=str(files[1]))
    result = _result(**{flag: False})
    assert not confirm_disputed_duration(ctx, result, repair)
    repair.confirm_duration.assert_not_called()
    assert not result.duration_ok


def test_confirmation_happens_before_remux_and_keeps_replace_gate_open(files):
    result = _result()
    ctx = SimpleNamespace(input_path=str(files[0]), output_path=str(files[1]), container="mkv",
                          analysis=SimpleNamespace(audio_streams=[object()]), duration_ms=2510082,
                          expected_media_contract=_contract())
    repair = SimpleNamespace(confirm_duration=Mock(return_value=(
        DurationVote("ffprobe/FFmpeg", True, "Videopakete bestätigen 2494.6 s"),
        DurationVote("MediaInfo", False, "Falsche Quellenreferenz"),
        DurationVote("MKVToolNix", True, "Zeitstempel bestätigen 2494.6 s"),
    )), can_repair=Mock(side_effect=AssertionError("unnecessary remux")))
    service = WorkflowVerificationService(output_verifier=SimpleNamespace(verify=lambda *a, **k: result),
                                         duration_repair_service=repair, logger=Mock())
    service.verify(ctx)
    assert ctx.verify_result.ok and ctx.keep_failed_output
    assert ctx.verify_result.messages == []
    assert len(ctx.verify_result.warnings) == 3
    assert files[0].read_bytes() == b"s" * 4096 and files[1].read_bytes() == b"o" * 4096
    repair.can_repair.assert_not_called()


def test_all_rejected_keep_existing_failure_and_archival(files, monkeypatch):
    result = _result()
    ctx = SimpleNamespace(input_path=str(files[0]), output_path=str(files[1]), container="mkv",
                          analysis=SimpleNamespace(audio_streams=[]), duration_ms=100000)
    repair = SimpleNamespace(confirm_duration=Mock(return_value=tuple(
        DurationVote(tool, False, "Videolaufzeit weicht ab") for tool in ("ffprobe", "MediaInfo", "MKVToolNix")
    )), can_repair=Mock(return_value=False))
    preserve = Mock()
    monkeypatch.setattr("dragontools.worker.workflow_verification_service.preserve_failed_verification_output", preserve)
    service = WorkflowVerificationService(output_verifier=SimpleNamespace(verify=lambda *a, **k: result),
                                         duration_repair_service=repair, logger=Mock())
    with pytest.raises(RuntimeError, match="Verify fehlgeschlagen"):
        service.verify(ctx)
    assert not result.duration_ok and not result.ok
    preserve.assert_called_once()


def test_packet_probe_uses_actual_pts_instead_of_mediainfo_frame_estimate(monkeypatch):
    monkeypatch.setattr("dragontools.worker.duration_confirmation_sources.tool_available", lambda _: True)
    seen = []
    def run(command, *, stdout_file=None, **kwargs):
        seen.append(command)
        if "-show_packets" in command:
            data = {"packets": [{"pts_time": str(p), "duration_time": "0.04"}
                                for p in (0.08, 0.16, 0.12)],
                    "streams": [{"codec_type": "video", "avg_frame_rate": "25/1"}]}
        else:
            data = {"format": {"duration": ".4"}, "streams": []}
        payload = json.dumps(data)
        if stdout_file is not None:
            stdout_file.write(payload)
            payload = ""
        return ToolRunResult(command, 0, stdout=payload)
    runtime = SimpleNamespace(ffprobe_path="ffprobe", mkvmerge_path="mkvmerge", worker=None, run_tool=run)
    sample = DurationConfirmationSources(runtime).ffprobe("video.mkv")
    assert sample.video_s == pytest.approx(.12) and sample.count == 3 and sample.measured
    assert "V:0" in seen[-1]  # attached cover images cannot become the program video


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "N/A"])
def test_invalid_packet_timestamps_are_not_confirmations(monkeypatch, bad):
    monkeypatch.setattr("dragontools.worker.duration_confirmation_sources.tool_available", lambda _: True)
    def run(command, *, stdout_file=None, **kwargs):
        data = ({"packets": [{"pts_time": bad, "duration_time": "0.04"}], "streams": []}
                if stdout_file is not None else {"format": {}, "streams": []})
        return ToolRunResult(command, 0, stdout=json.dumps(data))
    runtime = SimpleNamespace(ffprobe_path="ffprobe", mkvmerge_path="mkvmerge", worker=None, run_tool=run)
    with pytest.raises(ValueError):
        DurationConfirmationSources(runtime).ffprobe("video.mkv")


def test_timed_out_tool_cannot_confirm_even_with_valid_stdout(monkeypatch):
    monkeypatch.setattr("dragontools.worker.duration_confirmation_sources.tool_available", lambda _: True)
    runtime = SimpleNamespace(ffprobe_path="ffprobe", mkvmerge_path="mkvmerge", worker=None,
                              run_tool=lambda cmd, **kw: ToolRunResult(cmd, 0, stdout='{}', timed_out=True))
    with pytest.raises(RuntimeError, match="zeitüberschritten"):
        DurationConfirmationSources(runtime).ffprobe("video.mkv")


def test_mkv_timestamps_use_track_delay_and_last_frame_length(tmp_path):
    timestamps = tmp_path / "video.txt"
    timestamps.write_text("# timestamp format v2\n80\n120\n160\n", encoding="utf-8")
    duration, count, frame_s = read_mkv_timestamps(timestamps, {"default_duration": 40000000})
    assert duration == pytest.approx(.12) and count == 3 and frame_s == .04


def test_mkv_b_frames_are_measured_in_presentation_order(tmp_path):
    timestamps = tmp_path / "video.txt"
    timestamps.write_text("# timestamp format v2\n80\n160\n120\n", encoding="utf-8")
    duration, count, frame_s = read_mkv_timestamps(timestamps, {})
    assert duration == pytest.approx(.12) and count == 3 and frame_s == pytest.approx(.04)
