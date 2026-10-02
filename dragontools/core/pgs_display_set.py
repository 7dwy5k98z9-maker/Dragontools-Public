# -*- coding: utf-8 -*-
"""Robust timing parser for Blu-ray PGS/SUP display sets.

The parser intentionally does *not* decode palettes or RLE bitmap objects.
DragonTools only needs reliable visibility intervals for OCR.  Rendering stays
with FFmpeg, while this module owns the part FFprobe cannot model reliably:
PGS presentation-composition (PCS) show/update/clear events.

SUP segment layout (big endian)::

    'PG' | PTS:u32 | DTS:u32 | type:u8 | payload_size:u16 | payload

Relevant segment types are PDS (0x14), ODS (0x15), PCS (0x16), WDS (0x17)
and END (0x80).  A PCS with one or more composition objects makes a subtitle
visible; a PCS with zero objects clears the current composition.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterable


PGS_CLOCK_HZ = 90_000.0
PGS_MAGIC = b"PG"
PGS_HEADER_SIZE = 13
PGS_PTS_WRAP = 1 << 32

SEGMENT_PDS = 0x14
SEGMENT_ODS = 0x15
SEGMENT_PCS = 0x16
SEGMENT_WDS = 0x17
SEGMENT_END = 0x80

_SEGMENT_NAMES = {
    SEGMENT_PDS: "PDS",
    SEGMENT_ODS: "ODS",
    SEGMENT_PCS: "PCS",
    SEGMENT_WDS: "WDS",
    SEGMENT_END: "END",
}


@dataclass(frozen=True)
class PgsSegment:
    offset: int
    pts_s: float
    dts_s: float
    segment_type: int
    payload: bytes

    @property
    def name(self) -> str:
        return _SEGMENT_NAMES.get(self.segment_type, f"0x{self.segment_type:02X}")


@dataclass(frozen=True)
class PgsCompositionEvent:
    pts_s: float
    composition_number: int
    composition_state: int
    object_count: int
    complete_display_set: bool

    @property
    def visible(self) -> bool:
        return self.object_count > 0


@dataclass(frozen=True)
class PgsCueTiming:
    start_s: float
    end_s: float


@dataclass(frozen=True)
class PgsParseStats:
    segments: int = 0
    display_sets: int = 0
    complete_display_sets: int = 0
    incomplete_display_sets: int = 0
    visible_events: int = 0
    clear_events: int = 0
    malformed_segments: int = 0
    resync_count: int = 0
    unknown_segments: int = 0


@dataclass(frozen=True)
class PgsParseResult:
    cues: tuple[PgsCueTiming, ...]
    events: tuple[PgsCompositionEvent, ...]
    stats: PgsParseStats
    warnings: tuple[str, ...] = ()


@dataclass
class _MutableStats:
    segments: int = 0
    display_sets: int = 0
    complete_display_sets: int = 0
    incomplete_display_sets: int = 0
    visible_events: int = 0
    clear_events: int = 0
    malformed_segments: int = 0
    resync_count: int = 0
    unknown_segments: int = 0

    def freeze(self) -> PgsParseStats:
        return PgsParseStats(**self.__dict__)


@dataclass
class _PendingEvent:
    pts_s: float
    composition_number: int
    composition_state: int
    object_count: int
    complete: bool = False


def parse_pgs_sup_file(
    path: str | Path,
    *,
    default_last_duration_s: float = 4.0,
    max_last_duration_s: float = 8.0,
) -> PgsParseResult:
    """Parse a raw ``.sup`` file and derive visible subtitle intervals."""
    file_path = Path(path)
    with file_path.open("rb") as handle:
        return parse_pgs_sup_stream(
            handle,
            default_last_duration_s=default_last_duration_s,
            max_last_duration_s=max_last_duration_s,
        )


def parse_pgs_sup_bytes(
    data: bytes,
    *,
    default_last_duration_s: float = 4.0,
    max_last_duration_s: float = 8.0,
) -> PgsParseResult:
    """Convenience wrapper used by unit tests and diagnostics."""
    from io import BytesIO

    return parse_pgs_sup_stream(
        BytesIO(data),
        default_last_duration_s=default_last_duration_s,
        max_last_duration_s=max_last_duration_s,
    )


def parse_pgs_sup_stream(
    handle: BinaryIO,
    *,
    default_last_duration_s: float = 4.0,
    max_last_duration_s: float = 8.0,
) -> PgsParseResult:
    """Parse SUP segments with recovery after malformed bytes.

    Recovery is deliberately conservative: when the next header is not ``PG``
    the parser scans forward for the next magic marker and continues.  This
    lets one damaged display set degrade locally instead of discarding the
    entire subtitle stream.
    """
    data = handle.read()
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("PGS/SUP parser erwartet einen binären Stream.")
    raw = bytes(data)
    stats = _MutableStats()
    warnings: list[str] = []
    segments: list[PgsSegment] = []

    offset = 0
    previous_raw_pts: int | None = None
    pts_wrap_base = 0
    previous_raw_dts: int | None = None
    dts_wrap_base = 0

    while offset < len(raw):
        if len(raw) - offset < PGS_HEADER_SIZE:
            if any(raw[offset:]):
                stats.malformed_segments += 1
                warnings.append(
                    f"SUP-Ende enthält {len(raw) - offset} unvollständige Header-Bytes."
                )
            break

        if raw[offset:offset + 2] != PGS_MAGIC:
            next_offset = _find_next_pgs_header(raw, offset + 1)
            stats.malformed_segments += 1
            if next_offset < 0:
                warnings.append(
                    f"Ungültige SUP-Daten ab Offset {offset}; kein weiterer PG-Header gefunden."
                )
                break
            stats.resync_count += 1
            warnings.append(
                f"SUP-Resync: {next_offset - offset} Byte(s) zwischen Offset {offset} und {next_offset} übersprungen."
            )
            offset = next_offset
            continue

        raw_pts = int.from_bytes(raw[offset + 2:offset + 6], "big", signed=False)
        raw_dts = int.from_bytes(raw[offset + 6:offset + 10], "big", signed=False)
        seg_type = raw[offset + 10]
        payload_size = int.from_bytes(raw[offset + 11:offset + 13], "big", signed=False)
        payload_start = offset + PGS_HEADER_SIZE
        payload_end = payload_start + payload_size
        if payload_end > len(raw):
            stats.malformed_segments += 1
            warnings.append(
                f"Segment bei Offset {offset} ist abgeschnitten: erwartet {payload_size} Payload-Bytes, "
                f"vorhanden {max(0, len(raw) - payload_start)}."
            )
            # A bogus size can swallow later valid packets. Try to recover at
            # the next plausible magic marker instead of terminating blindly.
            next_offset = _find_next_pgs_header(raw, payload_start)
            if next_offset < 0:
                break
            stats.resync_count += 1
            offset = next_offset
            continue

        if previous_raw_pts is not None and raw_pts < previous_raw_pts and previous_raw_pts - raw_pts > (PGS_PTS_WRAP // 2):
            pts_wrap_base += PGS_PTS_WRAP
        if previous_raw_dts is not None and raw_dts < previous_raw_dts and previous_raw_dts - raw_dts > (PGS_PTS_WRAP // 2):
            dts_wrap_base += PGS_PTS_WRAP
        previous_raw_pts = raw_pts
        previous_raw_dts = raw_dts

        segment = PgsSegment(
            offset=offset,
            pts_s=(pts_wrap_base + raw_pts) / PGS_CLOCK_HZ,
            dts_s=(dts_wrap_base + raw_dts) / PGS_CLOCK_HZ,
            segment_type=seg_type,
            payload=raw[payload_start:payload_end],
        )
        segments.append(segment)
        stats.segments += 1
        if seg_type not in _SEGMENT_NAMES:
            stats.unknown_segments += 1
        offset = payload_end

    events = _composition_events(segments, stats=stats, warnings=warnings)
    cues = _events_to_cues(
        events,
        default_last_duration_s=default_last_duration_s,
        max_last_duration_s=max_last_duration_s,
    )
    return PgsParseResult(
        cues=tuple(cues),
        events=tuple(events),
        stats=stats.freeze(),
        warnings=tuple(warnings),
    )



def _find_next_pgs_header(raw: bytes, start: int) -> int:
    """Return the next structurally plausible SUP header or ``-1``.

    During corruption recovery a plain ``bytes.find(b"PG")`` can hit the
    letters inside compressed bitmap payload. A candidate is therefore only
    accepted when the full header fits, the segment type is a known PGS type
    and the declared payload stays inside the current buffer.
    """
    cursor = max(0, int(start))
    known_types = frozenset(_SEGMENT_NAMES)
    while True:
        candidate = raw.find(PGS_MAGIC, cursor)
        if candidate < 0:
            return -1
        if candidate + PGS_HEADER_SIZE <= len(raw):
            seg_type = raw[candidate + 10]
            payload_size = int.from_bytes(
                raw[candidate + 11:candidate + 13], "big", signed=False
            )
            if (
                seg_type in known_types
                and candidate + PGS_HEADER_SIZE + payload_size <= len(raw)
            ):
                return candidate
        cursor = candidate + 1

def _composition_events(
    segments: Iterable[PgsSegment],
    *,
    stats: _MutableStats,
    warnings: list[str],
) -> list[PgsCompositionEvent]:
    events: list[PgsCompositionEvent] = []
    pending: _PendingEvent | None = None

    def flush_pending(*, complete: bool) -> None:
        nonlocal pending
        if pending is None:
            return
        pending.complete = complete
        stats.display_sets += 1
        if complete:
            stats.complete_display_sets += 1
        else:
            stats.incomplete_display_sets += 1
        if pending.object_count > 0:
            stats.visible_events += 1
        else:
            stats.clear_events += 1
        events.append(PgsCompositionEvent(
            pts_s=pending.pts_s,
            composition_number=pending.composition_number,
            composition_state=pending.composition_state,
            object_count=pending.object_count,
            complete_display_set=complete,
        ))
        pending = None

    for segment in segments:
        if segment.segment_type == SEGMENT_PCS:
            # A new PCS before END means the previous display set is incomplete,
            # but its visibility event is still useful for timing/OCR.
            if pending is not None:
                warnings.append(
                    f"Display Set bei {pending.pts_s:.3f}s ohne END vor nächstem PCS."
                )
                flush_pending(complete=False)
            parsed = _parse_pcs(segment.payload)
            if parsed is None:
                stats.malformed_segments += 1
                warnings.append(
                    f"PCS bei {segment.pts_s:.3f}s ist zu kurz oder strukturell ungültig."
                )
                continue
            composition_number, composition_state, object_count = parsed
            pending = _PendingEvent(
                pts_s=segment.pts_s,
                composition_number=composition_number,
                composition_state=composition_state,
                object_count=object_count,
            )
        elif segment.segment_type == SEGMENT_END:
            if pending is not None:
                flush_pending(complete=True)

    if pending is not None:
        warnings.append(f"Letztes Display Set bei {pending.pts_s:.3f}s endet ohne END.")
        flush_pending(complete=False)

    events.sort(key=lambda event: event.pts_s)
    return events


def _parse_pcs(payload: bytes) -> tuple[int, int, int] | None:
    # PCS fixed fields end with number_of_composition_objects at byte 10.
    if len(payload) < 11:
        return None
    composition_number = int.from_bytes(payload[5:7], "big", signed=False)
    composition_state = payload[7]
    object_count = payload[10]

    # Validate the variable object list enough to reject obviously corrupted
    # object counts. Each entry has 8 bytes; cropped entries add another 8.
    cursor = 11
    for _ in range(object_count):
        if cursor + 8 > len(payload):
            return None
        crop_flag = payload[cursor + 3]
        cursor += 8
        if crop_flag & 0x80:
            if cursor + 8 > len(payload):
                return None
            cursor += 8
    return composition_number, composition_state, object_count


def _events_to_cues(
    events: Iterable[PgsCompositionEvent],
    *,
    default_last_duration_s: float,
    max_last_duration_s: float,
) -> list[PgsCueTiming]:
    ordered = sorted(events, key=lambda event: event.pts_s)
    cues: list[PgsCueTiming] = []
    active_start: float | None = None

    for event in ordered:
        pts = max(0.0, float(event.pts_s))
        if event.visible:
            if active_start is not None and pts > active_start + 0.01:
                cues.append(PgsCueTiming(active_start, pts))
            # A visible PCS replaces/updates the current composition. Treat it
            # as a new OCR sample; duplicate text is merged later by OCR logic.
            active_start = pts
        else:
            if active_start is not None:
                end = max(active_start + 0.05, pts)
                cues.append(PgsCueTiming(active_start, end))
                active_start = None

    if active_start is not None:
        duration = max(0.10, min(float(max_last_duration_s), float(default_last_duration_s)))
        cues.append(PgsCueTiming(active_start, active_start + duration))

    # Remove zero/near-duplicate timings caused by repeated PCS at one PTS.
    normalized: list[PgsCueTiming] = []
    for cue in cues:
        if cue.end_s <= cue.start_s + 0.01:
            continue
        if normalized and abs(normalized[-1].start_s - cue.start_s) < 0.01 and abs(normalized[-1].end_s - cue.end_s) < 0.01:
            continue
        normalized.append(cue)
    return normalized


__all__ = [
    "PGS_CLOCK_HZ",
    "SEGMENT_PDS",
    "SEGMENT_ODS",
    "SEGMENT_PCS",
    "SEGMENT_WDS",
    "SEGMENT_END",
    "PgsSegment",
    "PgsCompositionEvent",
    "PgsCueTiming",
    "PgsParseStats",
    "PgsParseResult",
    "parse_pgs_sup_file",
    "parse_pgs_sup_bytes",
    "parse_pgs_sup_stream",
]
