from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

from dragontools.worker.duration_packet_integrity import PacketIntegrityVerifier
from dragontools.worker.duration_repair_commands import build_timestamp_repair_command
from dragontools.worker.duration_repair_models import MediaTimingInfo
from dragontools.worker.duration_repair_validation import validate_timestamp_repair
from dragontools.worker.duration_timestamp_helpers import allow_one_frame_wrap_cfr_repair
from dragontools.worker.subtitle_sidecar_plan import select_sidecar_streams
from dragontools.worker.subtitle_sidecar_targets import build_sidecar_targets
from dragontools.worker.workflow_engine import WorkflowVerifyResult


def _stream(index: int, codec: str, language: str = "eng", forced: bool = False):
    return SimpleNamespace(index=index, codec=codec, language=language, forced=forced, title="")


def test_mkv_mov_text_is_transcoded_to_internal_srt():
    from dragontools.worker.converter_subtitle_args import _mkv_args

    decisions: list[str] = []
    worker = SimpleNamespace(_logger=SimpleNamespace(decision=decisions.append))
    mov = _stream(5, "mov_text", forced=True)
    srt = _stream(6, "subrip", language="deu")

    _burn, args = _mkv_args(worker, None, [mov, srt])

    assert "0:5" in args
    assert "0:6" in args
    pos5 = args.index("0:5")
    assert args[pos5 + 1:pos5 + 3] == ["-c:s:0", "srt"]
    pos6 = args.index("0:6")
    assert args[pos6 + 1:pos6 + 3] == ["-c:s:1", "copy"]
    assert any("#5" in line and "SRT intern" in line for line in decisions)


def test_mkv_mov_text_does_not_create_normal_sidecar_when_optional_sidecars_are_disabled():
    mov = _stream(5, "mov_text", forced=True)
    plan = SimpleNamespace(external_streams=(mov,), burn_sub=None)
    storage = SimpleNamespace(external_streams=(), internal_streams=(mov,))

    selection = select_sidecar_streams(
        [mov],
        audio_streams=[],
        media_duration_s=100.0,
        file_override=None,
        subtitle_rules={},
        preserve_burn_candidate=False,
        normalize_override=lambda value: value,
        compute_plan=lambda *_args, **_kwargs: plan,
        build_storage_plan=lambda *_args, **_kwargs: storage,
        sidecars_enabled=lambda _rules: False,
        additional_sidecars_enabled=lambda _rules: False,
        text_to_srt_sidecar_enabled=lambda _rules: False,
        container="mkv",
    )

    assert selection.normal_streams == ()
    assert selection.ass_srt_streams == ()

    targets, unsupported = build_sidecar_targets(
        selection.normal_streams,
        Path("/output/Film"),
        ass_srt_streams=selection.ass_srt_streams,
        language_tag=lambda value: "en",
        filename_builder=lambda base, lang, forced, ext, number: f"{base}.{lang}{'.forced' if forced else ''}{ext}",
        codec_resolver=lambda codec: (".srt", ["-c:s", "srt"]) if codec in {"mov_text", "tx3g"} else None,
    )
    assert unsupported == []
    assert targets == []


def test_mkvtoolnix_default_duration_command_uses_real_matroska_track_id():
    cmd = build_timestamp_repair_command(
        Path("broken.mkv"),
        Path("fixed.mkv"),
        Fraction(24000, 1001),
        container="mkv",
        mp4box_path="MP4Box",
        ffmpeg_path="ffmpeg",
        mkvmerge_path="mkvmerge",
        mkv_video_track_id=7,
    )

    assert cmd[:2] == ["mkvmerge", "--ui-language"]
    assert "--default-duration" in cmd
    assert cmd[cmd.index("--default-duration") + 1] == "7:24000/1001fps"
    assert "ffmpeg" not in cmd


def _ok_verify(duration_s: float) -> WorkflowVerifyResult:
    return WorkflowVerifyResult(
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
        duration_s=duration_s,
        video_stream_count=1,
        audio_stream_count=1,
        subtitle_stream_count=1,
        messages=[],
    )


def test_timestamp_validation_accepts_point_three_seconds_and_does_not_trust_audio_duration_alone():
    fps = Fraction(24000, 1001)
    before = MediaTimingInfo(
        path="broken.mkv",
        container_duration_s=4_295_637.5,
        video_duration_s=4_295_637.5,
        audio_duration_s=722.0,
        chapter_end_s=777.8,
        video_frame_count=18_649,
        frame_rate=fps,
        frame_rate_mode="CFR",
        video_stream_count=1,
        audio_stream_count=1,
        subtitle_stream_count=1,
    )
    repaired = MediaTimingInfo(
        path="fixed.mkv",
        container_duration_s=777.5,
        video_duration_s=777.5,
        audio_duration_s=722.0,  # unzuverlaessiges Stream-Duration-Metadatum
        chapter_end_s=777.8,
        video_frame_count=18_649,
        frame_rate=fps,
        frame_rate_mode="CFR",
        video_stream_count=1,
        audio_stream_count=1,
        subtitle_stream_count=1,
    )

    ok, messages = validate_timestamp_repair(
        before=before,
        repaired=repaired,
        verify_result=_ok_verify(777.5),
        expected_duration_ms=777_800,
        source_has_audio=True,
        stream_count_overrides={"video", "audio", "subtitle"},
        ignore_verify_stream_kinds={"video", "audio", "subtitle"},
    )

    assert ok is True, messages


def test_one_frame_vfr_difference_is_only_allowed_for_strong_wrap_signature():
    info = MediaTimingInfo(
        path="broken.mkv",
        container_duration_s=4_295_642.1,
        video_duration_s=4_295_642.3,
        video_frame_count=18_649,
        frame_rate=Fraction(24000, 1001),
        frame_rate_mode="VFR",
    )
    assert allow_one_frame_wrap_cfr_repair(
        info,
        expected_duration_s=777.8,
        fallback_reason="Frameanzahl stimmt nicht überein: Original=18648, Ausgabe=18649.",
    )
    assert not allow_one_frame_wrap_cfr_repair(
        info,
        expected_duration_s=777.8,
        fallback_reason="Frameanzahl stimmt nicht überein: Original=18647, Ausgabe=18649.",
    )


def _packet_payload(*, changed_audio_hash: bool = False, reordered: bool = False):
    packets = [
        {"stream_index": 0, "pts_time": "0.000", "dts_time": "0.000", "duration_time": "0.041708", "data_hash": "SHA256:V1"},
        {"stream_index": 1, "pts_time": "0.000", "dts_time": "0.000", "duration_time": "0.020", "data_hash": "SHA256:A1"},
        {"stream_index": 0, "pts_time": "0.041708", "dts_time": "0.041708", "duration_time": "0.041708", "data_hash": "SHA256:V2"},
        {"stream_index": 1, "pts_time": "0.020", "dts_time": "0.020", "duration_time": "0.020", "data_hash": "SHA256:A2_CHANGED" if changed_audio_hash else "SHA256:A2"},
    ]
    if reordered:
        # Globale Interleaving-Reihenfolge darf sich beim Remux aendern;
        # die Reihenfolge innerhalb jedes Streams bleibt erhalten.
        packets = [packets[1], packets[3], packets[0], packets[2]]
    return {
        "streams": [
            {"index": 0, "codec_type": "video"},
            {"index": 1, "codec_type": "audio"},
        ],
        "packets": packets,
    }


def test_packet_integrity_compares_hashes_per_stream_not_global_mux_order(monkeypatch):
    monkeypatch.setattr("dragontools.worker.duration_packet_integrity.tool_available", lambda _path: True)
    payloads = {
        "before.mkv": _packet_payload(),
        "after.mkv": _packet_payload(reordered=True),
    }

    def run_tool(cmd, *, label):
        return SimpleNamespace(returncode=0, stdout=json.dumps(payloads[str(cmd[-1])]), stderr="")

    verifier = PacketIntegrityVerifier(ffprobe_path="ffprobe", run_tool=run_tool)
    result = verifier.validate(
        "before.mkv",
        "after.mkv",
        reference_duration_s=1.0,
        frame_rate=Fraction(24000, 1001),
    )
    assert result.ok is True, result.messages
    assert result.available is True


def test_packet_integrity_rejects_changed_payload(monkeypatch):
    monkeypatch.setattr("dragontools.worker.duration_packet_integrity.tool_available", lambda _path: True)
    payloads = {
        "before.mkv": _packet_payload(),
        "after.mkv": _packet_payload(changed_audio_hash=True),
    }

    def run_tool(cmd, *, label):
        return SimpleNamespace(returncode=0, stdout=json.dumps(payloads[str(cmd[-1])]), stderr="")

    verifier = PacketIntegrityVerifier(ffprobe_path="ffprobe", run_tool=run_tool)
    result = verifier.validate(
        "before.mkv",
        "after.mkv",
        reference_duration_s=1.0,
        frame_rate=Fraction(24000, 1001),
    )
    assert result.ok is False
    assert any("Nutzdatenhashes" in message for message in result.messages)
