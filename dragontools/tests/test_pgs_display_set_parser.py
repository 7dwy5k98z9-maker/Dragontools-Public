from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from dragontools.core.bitmap_subtitle_ocr import BitmapSubtitlePacket
from dragontools.core.pgs_display_set import (
    SEGMENT_END,
    SEGMENT_ODS,
    SEGMENT_PCS,
    parse_pgs_sup_bytes,
)
from dragontools.worker.bitmap_subtitle_ocr_service import BitmapSubtitleOcrService


def _segment(pts_s: float, seg_type: int, payload: bytes = b"", *, dts_s: float | None = None) -> bytes:
    pts = int(round(pts_s * 90_000)) & 0xFFFFFFFF
    dts = int(round((pts_s if dts_s is None else dts_s) * 90_000)) & 0xFFFFFFFF
    return (
        b"PG"
        + pts.to_bytes(4, "big")
        + dts.to_bytes(4, "big")
        + bytes([seg_type])
        + len(payload).to_bytes(2, "big")
        + payload
    )


def _pcs(*, object_count: int, composition_number: int = 1, state: int = 0x00) -> bytes:
    payload = (
        (1920).to_bytes(2, "big")
        + (1080).to_bytes(2, "big")
        + b"\x10"
        + int(composition_number).to_bytes(2, "big")
        + bytes([state, 0x00, 0x00, object_count])
    )
    for object_id in range(1, object_count + 1):
        payload += (
            object_id.to_bytes(2, "big")
            + b"\x00"      # window id
            + b"\x00"      # not cropped
            + (100).to_bytes(2, "big")
            + (900).to_bytes(2, "big")
        )
    return payload


def _display_set(pts_s: float, *, visible: bool, composition_number: int) -> bytes:
    return (
        _segment(
            pts_s,
            SEGMENT_PCS,
            _pcs(object_count=1 if visible else 0, composition_number=composition_number),
        )
        + _segment(pts_s, SEGMENT_END)
    )


def test_visible_pcs_until_clear_becomes_exact_cue() -> None:
    raw = _display_set(1.0, visible=True, composition_number=1) + _display_set(
        3.25, visible=False, composition_number=2
    )
    parsed = parse_pgs_sup_bytes(raw)

    assert [(cue.start_s, cue.end_s) for cue in parsed.cues] == pytest.approx([(1.0, 3.25)])
    assert parsed.stats.display_sets == 2
    assert parsed.stats.complete_display_sets == 2
    assert parsed.stats.visible_events == 1
    assert parsed.stats.clear_events == 1
    assert parsed.stats.malformed_segments == 0


def test_visible_replacement_closes_previous_cue_and_starts_new_one() -> None:
    raw = (
        _display_set(1.0, visible=True, composition_number=1)
        + _display_set(2.0, visible=True, composition_number=2)
        + _display_set(4.0, visible=False, composition_number=3)
    )
    parsed = parse_pgs_sup_bytes(raw)

    assert [(cue.start_s, cue.end_s) for cue in parsed.cues] == pytest.approx(
        [(1.0, 2.0), (2.0, 4.0)]
    )


def test_fragmented_ods_inside_display_set_does_not_change_visibility_timing() -> None:
    raw = (
        _segment(5.0, SEGMENT_PCS, _pcs(object_count=1, composition_number=7))
        + _segment(5.0, SEGMENT_ODS, b"first-fragment")
        + _segment(5.0, SEGMENT_ODS, b"second-fragment")
        + _segment(5.0, SEGMENT_END)
        + _display_set(7.0, visible=False, composition_number=8)
    )
    parsed = parse_pgs_sup_bytes(raw)

    assert len(parsed.cues) == 1
    assert parsed.cues[0].start_s == pytest.approx(5.0)
    assert parsed.cues[0].end_s == pytest.approx(7.0)
    assert parsed.stats.segments == 6


def test_parser_resynchronizes_after_garbage_instead_of_losing_following_display_sets() -> None:
    raw = b"broken-data" + _display_set(10.0, visible=True, composition_number=1) + _display_set(
        12.0, visible=False, composition_number=2
    )
    parsed = parse_pgs_sup_bytes(raw)

    assert [(cue.start_s, cue.end_s) for cue in parsed.cues] == pytest.approx([(10.0, 12.0)])
    assert parsed.stats.resync_count == 1
    assert parsed.stats.malformed_segments >= 1
    assert parsed.warnings


def test_truncated_bogus_segment_recovers_at_next_pg_header() -> None:
    bogus = (
        b"PG"
        + int(1 * 90_000).to_bytes(4, "big")
        + int(1 * 90_000).to_bytes(4, "big")
        + bytes([SEGMENT_ODS])
        + (5000).to_bytes(2, "big")
        + b"bad"
    )
    raw = bogus + _display_set(20.0, visible=True, composition_number=1) + _display_set(
        21.0, visible=False, composition_number=2
    )
    parsed = parse_pgs_sup_bytes(raw)

    assert [(cue.start_s, cue.end_s) for cue in parsed.cues] == pytest.approx([(20.0, 21.0)])
    assert parsed.stats.resync_count >= 1
    assert parsed.stats.malformed_segments >= 1


def test_missing_end_marks_display_set_incomplete_but_keeps_timing() -> None:
    raw = (
        _segment(30.0, SEGMENT_PCS, _pcs(object_count=1, composition_number=1))
        + _segment(30.0, SEGMENT_ODS, b"object")
        + _display_set(32.0, visible=False, composition_number=2)
    )
    parsed = parse_pgs_sup_bytes(raw)

    assert [(cue.start_s, cue.end_s) for cue in parsed.cues] == pytest.approx([(30.0, 32.0)])
    assert parsed.stats.incomplete_display_sets == 1
    assert any("ohne END" in warning for warning in parsed.warnings)


def test_open_last_visible_display_set_gets_bounded_default_duration() -> None:
    parsed = parse_pgs_sup_bytes(_display_set(40.0, visible=True, composition_number=1))
    assert len(parsed.cues) == 1
    assert parsed.cues[0].start_s == pytest.approx(40.0)
    assert parsed.cues[0].end_s == pytest.approx(44.0)


class _Settings:
    def value(self, _key, default=None, type=None):
        return type(default) if type is not None else default


class _Tools:
    ffmpeg = "ffmpeg"
    ffprobe = "ffprobe"
    tesseract = "tesseract"
    mkvmerge = "mkvmerge"
    mkvextract = "mkvextract"


def test_ocr_service_uses_display_set_parser_before_ffprobe(monkeypatch, tmp_path: Path) -> None:
    service = BitmapSubtitleOcrService(settings=_Settings(), tools=_Tools())
    expected = [BitmapSubtitlePacket(1.0, 2.0)]
    monkeypatch.setattr(service, "_probe_pgs_display_sets", lambda *_args: expected)
    monkeypatch.setattr(
        service,
        "_probe_packets_ffprobe",
        lambda *_args: (_ for _ in ()).throw(AssertionError("FFprobe fallback must not run")),
    )

    assert service._probe_packets("Movie.mkv", 2, "ffprobe", codec="hdmv_pgs_subtitle") == expected


def test_ocr_service_falls_back_to_ffprobe_when_display_set_parser_has_no_cues(monkeypatch) -> None:
    logs = []
    service = BitmapSubtitleOcrService(
        settings=_Settings(), tools=_Tools(), log=lambda message, level="info": logs.append((level, message))
    )
    fallback = [BitmapSubtitlePacket(3.0, 4.0)]
    monkeypatch.setattr(service, "_probe_pgs_display_sets", lambda *_args: [])
    monkeypatch.setattr(service, "_probe_packets_ffprobe", lambda *_args: fallback)

    result = service._probe_packets("Movie.mkv", 2, "ffprobe", codec="pgs")
    assert result == fallback
    assert any("FFprobe-Timing" in message for _level, message in logs)


def test_service_parses_extracted_sup_and_logs_structure_stats(monkeypatch, tmp_path: Path) -> None:
    logs = []
    service = BitmapSubtitleOcrService(
        settings=_Settings(), tools=_Tools(), log=lambda message, level="info": logs.append((level, message))
    )

    def fake_extract(_path, _index, target, _ffprobe):
        target.write_bytes(
            _display_set(2.0, visible=True, composition_number=1)
            + _display_set(5.0, visible=False, composition_number=2)
        )
        return "MKVToolNix"

    monkeypatch.setattr(service, "_extract_pgs_sup", fake_extract)
    packets = service._probe_pgs_display_sets(str(tmp_path / "Movie.mkv"), 2, "ffprobe")

    assert packets == [BitmapSubtitlePacket(2.0, 5.0)]
    assert any("2 Display Sets" in message and "1 OCR-Cues" in message for _level, message in logs)


def test_pgs_extraction_prefers_mkvtoolnix_and_maps_subtitle_ordinal(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "Movie.mkv"
    source.write_bytes(b"mkv")
    target = tmp_path / "track.sup"
    service = BitmapSubtitleOcrService(settings=_Settings(), tools=_Tools())
    calls = []

    monkeypatch.setattr(
        "dragontools.worker.bitmap_subtitle_ocr_service.tool_available",
        lambda _tool: True,
    )

    def fake_run(cmd, **_kwargs):
        calls.append(list(cmd))
        if cmd[0] == "ffprobe":
            return SimpleNamespace(returncode=0, stdout='{"streams":[{"index":2},{"index":5}]}', stderr="")
        if cmd[0] == "mkvmerge":
            return SimpleNamespace(
                returncode=0,
                stdout='{"tracks":[{"id":0,"type":"video"},{"id":7,"type":"subtitles"},{"id":9,"type":"subtitles"}]}',
                stderr="",
            )
        if cmd[0] == "mkvextract":
            target.write_bytes(_display_set(1.0, visible=True, composition_number=1))
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        raise AssertionError(cmd)

    monkeypatch.setattr("dragontools.worker.bitmap_subtitle_ocr_service.run_analysis_tool", fake_run)
    backend = service._extract_pgs_sup(str(source), 5, target, "ffprobe")

    assert backend == "MKVToolNix"
    extract_cmd = next(cmd for cmd in calls if cmd[0] == "mkvextract")
    assert extract_cmd[-1].startswith("9:")
    assert not any(cmd[0] == "ffmpeg" for cmd in calls)


def test_partial_ffmpeg_sup_is_still_parsed_when_mkvtoolnix_unavailable(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "Movie.mkv"
    source.write_bytes(b"mkv")
    target = tmp_path / "track.sup"
    tools = SimpleNamespace(ffmpeg="ffmpeg", ffprobe="ffprobe", tesseract="tesseract", mkvmerge="", mkvextract="")
    service = BitmapSubtitleOcrService(settings=_Settings(), tools=tools)

    def fake_run(cmd, **_kwargs):
        target.write_bytes(_display_set(1.0, visible=True, composition_number=1))
        return SimpleNamespace(returncode=1, stdout="", stderr="Not enough data")

    monkeypatch.setattr("dragontools.worker.bitmap_subtitle_ocr_service.run_analysis_tool", fake_run)
    backend = service._extract_pgs_sup(str(source), 2, target, "ffprobe")
    assert backend == "FFmpeg-partiell"


def test_resync_ignores_pg_bytes_that_are_not_plausible_segment_headers() -> None:
    fake = b"noisePG" + b"\x00" * 8 + b"\xFF\xFF\xFF" + b"more-noise"
    raw = fake + _display_set(50.0, visible=True, composition_number=1) + _display_set(
        52.0, visible=False, composition_number=2
    )
    parsed = parse_pgs_sup_bytes(raw)
    assert [(cue.start_s, cue.end_s) for cue in parsed.cues] == pytest.approx([(50.0, 52.0)])
    assert parsed.stats.resync_count == 1


def test_mkvextract_runtime_failure_falls_back_to_ffmpeg(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "Movie.mkv"
    source.write_bytes(b"mkv")
    target = tmp_path / "track.sup"
    service = BitmapSubtitleOcrService(settings=_Settings(), tools=_Tools())

    monkeypatch.setattr(
        "dragontools.worker.bitmap_subtitle_ocr_service.tool_available",
        lambda _tool: True,
    )
    monkeypatch.setattr(service, "_mkv_track_id_for_stream", lambda *_args: 7)

    def fake_run(cmd, **_kwargs):
        if cmd[0] == "mkvextract":
            raise RuntimeError("timeout")
        if cmd[0] == "ffmpeg":
            target.write_bytes(_display_set(1.0, visible=True, composition_number=1))
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        raise AssertionError(cmd)

    monkeypatch.setattr("dragontools.worker.bitmap_subtitle_ocr_service.run_analysis_tool", fake_run)
    assert service._extract_pgs_sup(str(source), 2, target, "ffprobe") == "FFmpeg"


def test_packet_probe_honors_abort_before_extracting_pgs() -> None:
    worker = SimpleNamespace(abort_requested=True, abort_type="sofort")
    service = BitmapSubtitleOcrService(settings=_Settings(), tools=_Tools(), worker=worker)
    with pytest.raises(RuntimeError, match="abgebrochen"):
        service._probe_packets("Movie.mkv", 2, "ffprobe", "pgs")
