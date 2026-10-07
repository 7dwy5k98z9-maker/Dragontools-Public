from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def _patch_probe(monkeypatch, payload: dict):
    import dragontools.worker.output_verifier as module

    def fake_run(*_args, **_kwargs):
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)


def _video_payload(*, duration: float, container: str = "matroska,webm", extra_streams=()):
    return {
        "format": {"format_name": container, "duration": str(duration)},
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "hevc",
                "pix_fmt": "yuv420p10le",
                "width": 1920,
                "height": 1080,
            },
            *extra_streams,
        ],
    }


def test_final_gate_rejects_five_percent_truncation_even_with_legacy_ratio(tmp_path, monkeypatch):
    from dragontools.worker.output_verifier import OutputVerifier

    out = tmp_path / "film.mkv"
    out.write_bytes(b"x" * 4096)
    _patch_probe(monkeypatch, _video_payload(duration=95.0))

    result = OutputVerifier(
        ffprobe_path="ffprobe",
        duration_min_ratio=0.90,
    ).verify(str(out), "mkv", expected_duration_ms=100_000)

    assert result.ok is False
    assert result.duration_ok is False
    assert any("dauer" in message.lower() for message in result.messages)


def test_final_gate_allows_small_container_rounding_delta(tmp_path, monkeypatch):
    from dragontools.worker.output_verifier import OutputVerifier

    out = tmp_path / "film.mkv"
    out.write_bytes(b"x" * 4096)
    _patch_probe(monkeypatch, _video_payload(duration=98.5))

    result = OutputVerifier(ffprobe_path="ffprobe").verify(
        str(out), "mkv", expected_duration_ms=100_000
    )

    assert result.ok is True


def test_final_gate_rejects_large_overrun_despite_legacy_upper_defaults(tmp_path, monkeypatch):
    from dragontools.worker.output_verifier import OutputVerifier

    out = tmp_path / "film.mkv"
    out.write_bytes(b"x" * 4096)
    _patch_probe(monkeypatch, _video_payload(duration=105.0))

    result = OutputVerifier(
        ffprobe_path="ffprobe",
        duration_max_ratio=1.25,
        duration_max_extra_s=60,
    ).verify(str(out), "mkv", expected_duration_ms=100_000)

    assert result.ok is False
    assert result.duration_ok is False


def test_duration_gate_rejects_non_finite_values():
    from dragontools.worker.output_verifier import OutputVerifier

    verifier = OutputVerifier(ffprobe_path="ffprobe")
    assert verifier._duration_plausible(float("nan"), expected_duration_ms=100_000) is False
    assert verifier._duration_plausible(float("inf"), expected_duration_ms=100_000) is False


def test_media_contract_container_cannot_drift_from_workflow_container(tmp_path, monkeypatch):
    from dragontools.worker.media_contract import ExpectedMediaContract
    from dragontools.worker.output_verifier import OutputVerifier

    out = tmp_path / "film.mkv"
    out.write_bytes(b"x" * 4096)
    _patch_probe(monkeypatch, _video_payload(duration=100.0))
    contract = ExpectedMediaContract(
        container="mp4",
        video_codec="hevc",
        video_stream_count=1,
        audio_tracks=(),
        subtitle_tracks=(),
        min_video_bit_depth=10,
    )

    result = OutputVerifier(ffprobe_path="ffprobe").verify(
        str(out), "mkv", expected_duration_ms=100_000, expected_contract=contract
    )

    assert result.ok is False
    assert result.contract_ok is False
    assert result.contract_non_geometry_ok is False
    assert any("Container-Vertrag" in message for message in result.messages)


def test_attached_picture_does_not_satisfy_program_video_gate(tmp_path, monkeypatch):
    from dragontools.worker.output_verifier import OutputVerifier

    out = tmp_path / "cover.mp4"
    out.write_bytes(b"x" * 4096)
    _patch_probe(
        monkeypatch,
        {
            "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "100"},
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "mjpeg",
                    "disposition": {"attached_pic": 1, "default": 0, "forced": 0},
                }
            ],
        },
    )

    result = OutputVerifier(ffprobe_path="ffprobe").verify(
        str(out), "mp4", expected_duration_ms=100_000
    )

    assert result.ok is False
    assert result.video_ok is False
    assert result.video_stream_count == 0
    assert result.attachment_stream_count == 1


def test_output_probe_requests_default_forced_and_attached_pic_dispositions(tmp_path):
    from dragontools.worker.output_probe import probe_output

    captured = {}

    def fake_run(command, **_kwargs):
        captured["command"] = command
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"format": {"format_name": "matroska", "duration": "1"}, "streams": []}),
            stderr="",
        )

    probe_output(
        tmp_path / "film.mkv",
        ffprobe_path="ffprobe",
        run_process=fake_run,
        no_window_kwargs={},
    )

    command = captured["command"]
    show_entries = command[command.index("-show_entries") + 1]
    assert "stream_disposition=default,forced,attached_pic" in show_entries


def test_recovery_never_deletes_source_from_prepared_container_change(tmp_path):
    from dragontools.core.replace_journal import ReplaceJournal, list_replace_journals, recover_active_replace_journals

    source = tmp_path / "movie.mkv"
    staging = tmp_path / "movie.__new__.mp4"
    destination = tmp_path / "movie.mp4"
    source.write_bytes(b"OLD" * 2048)
    staging.write_bytes(b"NEW" * 2048)
    ReplaceJournal.start(
        source=source,
        destination=destination,
        staging=staging,
        backup=None,
        mode="container_change",
        root=tmp_path,
    )

    # Simuliert harten Crash direkt nach os.replace(staging, destination),
    # aber vor durable set_status("committed").
    staging.replace(destination)
    result = recover_active_replace_journals(tmp_path)

    assert result["cleaned_sources"] == 0
    assert result["pending"] == 1
    assert source.read_bytes() == b"OLD" * 2048
    assert destination.read_bytes() == b"NEW" * 2048
    assert len(list_replace_journals(tmp_path)) == 1


def test_same_path_recovery_restores_original_when_commit_status_was_not_durable(tmp_path):
    from dragontools.core.replace_journal import ReplaceJournal, list_replace_journals, recover_active_replace_journals

    destination = tmp_path / "movie.mkv"
    staging = tmp_path / "movie.__new__.mkv"
    backup = tmp_path / "movie.mkv.dragontools_backup"
    destination.write_bytes(b"OLD" * 2048)
    staging.write_bytes(b"NEW" * 2048)
    ReplaceJournal.start(
        source=destination,
        destination=destination,
        staging=staging,
        backup=backup,
        mode="same_path",
        root=tmp_path,
    )

    # Simuliert PathSwapTransaction: Original -> Backup, Staging -> Ziel,
    # danach harter Crash noch vor set_status("committed").
    destination.replace(backup)
    staging.replace(destination)

    result = recover_active_replace_journals(tmp_path)

    assert result["restored"] == 1
    assert destination.read_bytes() == b"OLD" * 2048
    assert staging.read_bytes() == b"NEW" * 2048
    assert not backup.exists()
    assert not list_replace_journals(tmp_path)


def test_container_change_journal_write_failure_rolls_back_visible_destination(tmp_path, monkeypatch):
    import dragontools.core.output_replace as module
    from dragontools.core.replace_journal import ReplaceJournalWriteError

    source = tmp_path / "movie.mkv"
    staging = tmp_path / "movie.__new__.mp4"
    destination = tmp_path / "movie.mp4"
    source.write_bytes(b"OLD" * 2048)
    staging.write_bytes(b"NEW" * 2048)

    real_set_status = module.ReplaceJournal.set_status

    def fail_committed(self, status: str, **kwargs):
        if status == "committed":
            raise ReplaceJournalWriteError("simulated disk full")
        return real_set_status(self, status, **kwargs)

    monkeypatch.setattr(module.ReplaceJournal, "set_status", fail_committed)

    with pytest.raises(ReplaceJournalWriteError, match="disk full"):
        module.commit_staged_output(
            source=source,
            staging=staging,
            destination=destination,
            log=lambda *_args: None,
            journal_root=tmp_path,
        )

    assert source.read_bytes() == b"OLD" * 2048
    assert staging.read_bytes() == b"NEW" * 2048
    assert not destination.exists()


def test_replace_service_propagates_immediate_abort_into_atomic_commit(tmp_path, monkeypatch):
    import dragontools.core.output_replace as output_replace
    from dragontools.worker.replace_service import ReplaceService

    source = tmp_path / "movie.mkv"
    staging = tmp_path / "movie.__new__.mp4"
    destination = tmp_path / "movie.mp4"
    source.write_bytes(b"OLD" * 2048)
    staging.write_bytes(b"NEW" * 2048)
    aborted = {"value": False}

    real_set_status = output_replace.ReplaceJournal.set_status

    def mark_abort_after_commit(self, status: str, **kwargs):
        result = real_set_status(self, status, **kwargs)
        if status == "committed":
            aborted["value"] = True
        return result

    monkeypatch.setattr(output_replace.ReplaceJournal, "set_status", mark_abort_after_commit)
    service = ReplaceService(
        overwrite_original=True,
        log=lambda *_args: None,
        journal_root=tmp_path,
        abort_check=lambda: aborted["value"],
    )

    with pytest.raises(RuntimeError, match="Abgebrochen"):
        service.replace(input_path=str(source), output_path=str(staging), container="mp4")

    assert source.read_bytes() == b"OLD" * 2048
    assert staging.read_bytes() == b"NEW" * 2048
    assert not destination.exists()


def test_rejected_timestamp_candidate_is_preserved_if_archive_commit_fails(tmp_path, monkeypatch):
    from dragontools.worker.duration_timestamp_candidate_archive import RejectedTimestampArchive

    tmp = tmp_path / "candidate.mkv"
    out = tmp_path / "film.mkv"
    tmp.write_bytes(b"candidate" * 1024)
    out.write_bytes(b"original" * 1024)
    deleted = []
    runtime = SimpleNamespace(
        replace_file=lambda *_args: (_ for _ in ()).throw(OSError("disk full")),
        safe_unlink=lambda path: deleted.append(str(path)),
        log=lambda *_args: None,
    )

    monkeypatch.setattr('dragontools.worker.duration_timestamp_candidate_archive.preserve_recovery_file',
        lambda *_: (_ for _ in ()).throw(OSError('disk full')))
    archived = RejectedTimestampArchive(runtime).archive(
        tmp,
        out=out,
        base_dir=tmp_path,
        label="verify-failed",
        reason="contract mismatch",
    )

    assert archived is None
    assert tmp.exists()
    assert deleted == []


def test_verified_duration_remux_candidate_survives_commit_failure(tmp_path):
    from dragontools.worker.duration_remux_service import DurationRemuxService
    from dragontools.worker.workflow_engine import WorkflowVerifyResult

    out = tmp_path / "film.mkv"
    out.write_bytes(b"ORIGINAL" * 1024)

    accepted = WorkflowVerifyResult(
        exists=True,
        size_ok=True,
        container_ok=True,
        probe_ok=True,
        video_ok=True,
        audio_ok=True,
        subtitle_ok=True,
        contract_ok=True,
        metadata_ok=True,
        duration_ok=True,
        duration_s=100.0,
        messages=[],
    )
    verifier = SimpleNamespace(verify=lambda *_args, **_kwargs: accepted)
    removed = []

    def run_tool(command, *, label):
        target = Path(command[command.index("-o") + 1])
        target.write_bytes(b"VERIFIED" * 1024)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    runtime = SimpleNamespace(
        mkvmerge_path="mkvmerge",
        mp4box_path="mp4box",
        run_tool=run_tool,
        output_verifier=verifier,
        replace_file=lambda *_args: (_ for _ in ()).throw(PermissionError("target locked")),
        safe_unlink=lambda path: (removed.append(str(path)), Path(path).unlink(missing_ok=True)),
        log=lambda *_args: None,
    )

    service = DurationRemuxService(runtime)
    service._packet_integrity = SimpleNamespace(validate=lambda *a,**kw:
        SimpleNamespace(ok=True,available=True,messages=[]))
    result, duration_s, repaired, message = service.attempt(
        out=out,
        container="mkv",
        expected_duration_ms=100_000,
        source_has_audio=True,
        initial_result=WorkflowVerifyResult(duration_ok=False, messages=["bad duration"]),
    )

    candidates = list(tmp_path.glob("film.duration_remux_*.mkv"))
    assert repaired is False
    assert duration_s == 100.0
    assert "nicht committed" in message
    assert out.read_bytes() == b"ORIGINAL" * 1024
    assert len(candidates) == 1
    assert candidates[0].read_bytes() == b"VERIFIED" * 1024
    assert str(candidates[0]) not in removed


def test_timestamp_service_archives_candidate_on_late_validation_exception(tmp_path, monkeypatch):
    from fractions import Fraction

    from dragontools.worker.duration_repair_models import MediaTimingInfo
    from dragontools.worker.duration_timestamp_service import TimestampRepairService
    from dragontools.worker.workflow_engine import WorkflowVerifyResult

    out = tmp_path / "film.mp4"
    out.write_bytes(b"ORIGINAL" * 1024)

    def replace_file(src, dst):
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        Path(src).replace(dst)

    runtime = SimpleNamespace(
        mkvmerge_path="mkvmerge",
        mp4box_path="mp4box",
        ffmpeg_path="ffmpeg",
        ffprobe_path="ffprobe",
        mediainfo_path="mediainfo",
        output_verifier=SimpleNamespace(),
        log=lambda *_args: None,
        run_tool=lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
        replace_file=replace_file,
        safe_unlink=lambda path: Path(path).unlink(missing_ok=True),
    )
    analyzer = SimpleNamespace()
    service = TimestampRepairService(runtime, analyzer)

    def explode_after_candidate_created(**kwargs):
        Path(kwargs["tmp"]).write_bytes(b"CANDIDATE" * 1024)
        raise RuntimeError("late validator crash")

    monkeypatch.setattr(service, "_attempt_candidate", explode_after_candidate_created)
    before = MediaTimingInfo(
        path=str(out),
        frame_rate=Fraction(25, 1),
        video_frame_count=2500,
        video_stream_count=1,
    )
    inventory = SimpleNamespace()

    result = service.repair_video_timestamps(
        out=out,
        container="mp4",
        base_dir=tmp_path,
        expected_duration_ms=100_000,
        source_has_audio=False,
        before=before,
        timing_summary=[],
        before_ffprobe=inventory,
        before_mediainfo=inventory,
        before_mkvmerge=inventory,
    )

    archived = list((tmp_path / "Archiv" / "Timestamp_Reparatur").glob("*.mp4"))
    assert result.repaired is False
    assert "late validator crash" in result.reason
    assert out.read_bytes() == b"ORIGINAL" * 1024
    assert len(archived) == 1
    assert archived[0].read_bytes() == b"CANDIDATE" * 1024


def test_original_vfr_timeline_archives_candidate_on_late_exception(tmp_path, monkeypatch):
    from dragontools.worker.duration_original_timeline_service import (
        OriginalTimelineRepairService,
        SourceVideoTimeline,
    )
    from dragontools.worker.duration_repair_models import MediaTimingInfo
    from dragontools.worker.workflow_engine import WorkflowVerifyResult

    source = tmp_path / "source.mkv"
    out = tmp_path / "film.mkv"
    source.write_bytes(b"SOURCE" * 1024)
    out.write_bytes(b"ORIGINAL" * 1024)

    def replace_file(src, dst):
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        Path(src).replace(dst)

    def run_tool(command, *, label):
        target = Path(command[command.index("-o") + 1])
        target.write_bytes(b"VFR-CANDIDATE" * 1024)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    runtime = SimpleNamespace(
        mkvmerge_path="mkvmerge",
        ffprobe_path="ffprobe",
        mediainfo_path="mediainfo",
        output_verifier=SimpleNamespace(),
        log=lambda *_args: None,
        run_tool=run_tool,
        replace_file=replace_file,
        safe_unlink=lambda path: Path(path).unlink(missing_ok=True),
    )
    source_info = MediaTimingInfo(path=str(source), video_frame_count=2, audio_duration_s=2.0)
    analyzer = SimpleNamespace(get_media_timing_info=lambda *_args, **_kwargs: source_info)
    guard = SimpleNamespace(inspect_pair=lambda *_args: (SimpleNamespace(), SimpleNamespace()))
    service = OriginalTimelineRepairService(runtime, analyzer, guard)

    monkeypatch.setattr(service, "_eligibility_error", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(service, "_read_source_timeline", lambda *_args: SourceVideoTimeline((0.0, 1.0), 2.0))
    monkeypatch.setattr(service, "_source_timeline_error", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(service, "_mkv_video_track_id", lambda *_args: 0)
    monkeypatch.setattr(
        service,
        "_write_timecodes_v2",
        lambda path, _timeline: Path(path).write_text("# timestamp format v2\n0\n1000\n", encoding="utf-8"),
    )
    monkeypatch.setattr(
        service,
        "_validate_candidate",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("late VFR validator crash")),
    )

    result = service.try_repair(
        source=source,
        out=out,
        base_dir=tmp_path,
        container="mkv",
        expected_duration_ms=2_000,
        expected_duration_s=2.0,
        source_has_audio=True,
        reference_result=WorkflowVerifyResult(duration_ok=False, messages=[]),
        before=MediaTimingInfo(path=str(out), video_frame_count=2),
        timing_summary=[],
    )

    archived = list((tmp_path / "Archiv" / "Timestamp_Reparatur").glob("*.mkv"))
    assert result.repaired is False
    assert "late VFR validator crash" in result.reason
    assert out.read_bytes() == b"ORIGINAL" * 1024
    assert len(archived) == 1
    assert archived[0].read_bytes() == b"VFR-CANDIDATE" * 1024
    assert not list(tmp_path.glob("*.source_timestamps_*.txt"))
