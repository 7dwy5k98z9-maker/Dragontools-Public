"""Audio-tail false positives and ownership-safe repair-copy cleanup."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from dragontools.worker.media_contract_types import ExpectedAudioTrack, ExpectedMediaContract
from dragontools.worker.output_duration_policy import output_duration_plausible
from dragontools.worker.output_probe import OutputProbeData
from dragontools.worker.output_verifier import OutputVerifier
from dragontools.worker.duration_repair_diagnostics import (
    RejectedRepairCandidates, cleanup_successful_repair_diagnostics,
)


def valid_duration(*, video=2548.421, audio=2559.648, container=2559.726, source_audio=2559.648):
    probe = OutputProbeData("matroska,webm", container, (
        {"codec_type": "video", "duration": video},
        {"codec_type": "audio", "duration": audio},
    ))
    contract = ExpectedMediaContract("mkv", "hevc", 1,
        (ExpectedAudioTrack("ac3", 6, duration_s=source_audio),), ())
    return output_duration_plausible(
        probe, expected_duration_ms=2548421, expected_contract=contract,
        plausible=OutputVerifier(ffprobe_path="ffprobe")._duration_plausible,
    )


def test_known_selected_audio_tail_does_not_trigger_video_timestamp_repair():
    assert valid_duration()


@pytest.mark.parametrize("changed", [
    {"video": 2400.0},
    {"video": 4297515.717},
    {"container": 4297527.022},
    {"audio": 2659.648, "container": 2659.726},
    {"source_audio": None},
    {"source_audio": 2548.421},
])
def test_audio_tail_never_excuses_truncation_wrap_or_unconfirmed_timing(changed):
    assert not valid_duration(**changed)


def test_mkv_duration_tags_account_for_stream_start_offsets():
    probe = OutputProbeData("matroska,webm", 2559.726, (
        {"codec_type": "video", "start_time": "0.083", "tags": {"DURATION": "00:42:28.504"}},
        {"codec_type": "audio", "start_time": "0.078", "tags": {"DURATION": "00:42:39.726"}},
    ))
    contract = ExpectedMediaContract("mkv", "hevc", 1,
        (ExpectedAudioTrack("ac3", 6, duration_s=2559.648),), ())
    assert output_duration_plausible(probe, expected_duration_ms=2548421, expected_contract=contract,
        plausible=OutputVerifier(ffprobe_path="ffprobe")._duration_plausible)


def diagnostic(tmp_path):
    folder = tmp_path / "Archiv" / "Timestamp_Reparatur"
    folder.mkdir(parents=True)
    path = folder / "episode.rejected.mkv"
    path.write_bytes(b"rejected attempt")
    collection = RejectedRepairCandidates()
    collection.record(path)
    return path, collection


def test_mkvtoolnix_track_length_keeps_independent_video_start_delay():
    probe = OutputProbeData("matroska,webm", 2.760, (
        {"codec_type": "video", "start_time": "0.8", "tags": {
            "DURATION": "00:00:01.960", "_STATISTICS_WRITING_APP": "mkvmerge v101.0",
            "_STATISTICS_TAGS": "BPS DURATION NUMBER_OF_FRAMES NUMBER_OF_BYTES",
        }},
    ))
    assert output_duration_plausible(probe, expected_duration_ms=1960, expected_contract=None,
        plausible=OutputVerifier(ffprobe_path="ffprobe")._duration_plausible)


@pytest.mark.parametrize("writer_tag", ["encoder", "ENCODER"])
def test_real_ffmpeg_writer_overrides_copied_metadata(writer_tag):
    from dragontools.core.media_duration import stream_duration, source_duration
    stream = {"codec_type": "video", "start_time": "0.8", "tags": {
        "DURATION": "00:00:02.760", "_STATISTICS_WRITING_APP": "mkvmerge v101.0",
        "_STATISTICS_TAGS": "BPS DURATION NUMBER_OF_FRAMES NUMBER_OF_BYTES",
    }}
    assert stream_duration(stream, writing_application="Lavf63.7.100") == pytest.approx(1.960)
    assert source_duration({"format": {"duration": "2.760", "tags": {writer_tag: "old arbitrary encoder"}},
                            "streams": [stream]}, writing_application="Lavf63.7.100") == pytest.approx(1.960)


def test_probe_uses_real_container_writer_instead_of_copied_encoder_tag(monkeypatch):
    import json
    from dragontools.worker.output_probe import probe_output
    data = {"format": {"format_name": "matroska,webm", "duration": "2.760",
                       "tags": {"ENCODER": "Lavf63.7.100"}}, "streams": []}
    monkeypatch.setattr("dragontools.worker.output_probe.matroska_writing_application", lambda _: "mkvmerge v101.0")
    result = probe_output(Path("fake.mkv"), ffprobe_path="ffprobe", no_window_kwargs={},
        run_process=lambda *_a, **_kw: SimpleNamespace(returncode=0, stdout=json.dumps(data), stderr=""))
    assert result.writing_application == "mkvmerge v101.0"


def test_matroska_writer_reader_is_bounded_and_rejects_incomplete_headers(tmp_path):
    from dragontools.core.matroska_writer import matroska_writing_application
    app = b"Lavf63.7.100"
    writing_app = bytes.fromhex("5741") + bytes([0x80 | len(app)]) + app
    info = bytes.fromhex("1549a966") + bytes([0x80 | len(writing_app)]) + writing_app
    data = bytes.fromhex("1a45dfa3801853806701ffffffffffffff") + info
    path = tmp_path / "header.mkv"
    path.write_bytes(data + b"\0" * 100000)
    assert matroska_writing_application(path) == app.decode()
    path.write_bytes(data[:-3])
    assert matroska_writing_application(path) == ""


def context(receipts, *, success=True, verified=True):
    return SimpleNamespace(success=success, verify_result=SimpleNamespace(ok=verified),
                           duration_repair_rejected_candidates=receipts)


def test_success_cleanup_removes_only_current_run_receipts(tmp_path):
    path, collection = diagnostic(tmp_path)
    unrelated = path.with_name("another-run.mkv")
    unrelated.write_bytes(b"keep this diagnostic")
    messages = []
    cleanup_successful_repair_diagnostics(context(collection.receipts), lambda *args: messages.append(args))
    assert not path.exists() and unrelated.is_file()
    assert messages and "1 verworfene" in messages[0][0]


@pytest.mark.parametrize("success,verified", [(False, True), (True, False), (False, False)])
def test_failed_processing_keeps_diagnostic_copies(tmp_path, success, verified):
    path, collection = diagnostic(tmp_path)
    cleanup_successful_repair_diagnostics(context(collection.receipts, success=success, verified=verified), lambda *_: None)
    assert path.is_file()


def test_changed_diagnostic_is_preserved_instead_of_deleted(tmp_path):
    path, collection = diagnostic(tmp_path)
    path.write_bytes(b"the user replaced the archived file")
    cleanup_successful_repair_diagnostics(context(collection.receipts), lambda *_: None)
    assert path.read_bytes() == b"the user replaced the archived file"


def test_new_repair_collection_does_not_inherit_older_run_receipts(tmp_path):
    path, collection = diagnostic(tmp_path)
    collection.clear()
    cleanup_successful_repair_diagnostics(context(collection.receipts), lambda *_: None)
    assert path.is_file()
