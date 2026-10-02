# -*- coding: utf-8 -*-
"""Conservative partial repair for rare DV encode frame-count mismatches.

The normal DV path encodes pictures directly from the source Matroska.  If the
completed HEVC still contains fewer pictures than the normalized RPU, this
module can try to preserve the good majority of the encode:

* build tiny perceptual dHash fingerprints for source and encoded pictures,
* align both sequences and locate the bounded deletion region,
* expand the region to HEVC IRAP access points,
* re-encode only that source-frame interval with the exact encoder/filter plan,
* splice prefix + replacement + suffix into a candidate bitstream,
* accept the candidate only after full decode, exact frame count and visual
  boundary fingerprints agree with the source timeline.

It is deliberately conservative.  Any ambiguity returns ``False`` and leaves
the existing diagnostic/archive path in control.
"""
from __future__ import annotations

from dataclasses import dataclass
import mmap
from pathlib import Path
from typing import Callable, Iterable

from .command_formatting import command_to_log_string as _cmd_str
from .dv_encode_command import build_dv_encode_command
from .dv_pipeline_timeouts import timeout_encode as _TIMEOUT_ENCODE


_FINGERPRINT_WIDTH = 9
_FINGERPRINT_HEIGHT = 8
_FINGERPRINT_BYTES = _FINGERPRINT_WIDTH * _FINGERPRINT_HEIGHT
_SAFE_BLA_IDR_TYPES = {16, 17, 18, 19, 20}
_IRAP_TYPES = _SAFE_BLA_IDR_TYPES | {21}
_PARAMETER_SET_TYPES = {32, 33, 34}


@dataclass(frozen=True)
class GapRegion:
    encoded_start: int
    encoded_end: int
    delta: int
    observations: int


@dataclass(frozen=True)
class IrapPoint:
    frame_index: int
    byte_offset: int
    nal_type: int

    @property
    def is_strong_boundary(self) -> bool:
        return self.nal_type in _SAFE_BLA_IDR_TYPES


@dataclass(frozen=True)
class RepairWindow:
    encoded_start: int
    encoded_end: int
    source_start: int
    source_end: int
    prefix_byte_end: int
    suffix_byte_start: int
    suffix_is_strong_boundary: bool

    @property
    def replacement_frames(self) -> int:
        return max(0, self.source_end - self.source_start)


def _frame_dhash(frame: bytes) -> int:
    """Return a 64-bit horizontal difference hash for a 9x8 gray frame."""
    if len(frame) != _FINGERPRINT_BYTES:
        raise ValueError("invalid fingerprint frame size")
    value = 0
    bit = 0
    for y in range(_FINGERPRINT_HEIGHT):
        row = y * _FINGERPRINT_WIDTH
        for x in range(_FINGERPRINT_WIDTH - 1):
            if frame[row + x] > frame[row + x + 1]:
                value |= 1 << bit
            bit += 1
    return value


def read_dhash_file(path: Path) -> list[int]:
    data = path.read_bytes()
    if not data or len(data) % _FINGERPRINT_BYTES:
        return []
    return [
        _frame_dhash(data[pos : pos + _FINGERPRINT_BYTES])
        for pos in range(0, len(data), _FINGERPRINT_BYTES)
    ]


def _block_alignment_score(
    source: list[int],
    encoded: list[int],
    *,
    encoded_start: int,
    source_offset: int,
    block_frames: int = 16,
) -> float:
    """Average dHash distance for a short temporal block.

    Comparing a block instead of one frame is important for animation, fades
    and static shots where adjacent frames can have nearly identical hashes.
    """
    distances: list[int] = []
    stop = min(len(encoded), encoded_start + max(4, int(block_frames)))
    for enc_idx in range(encoded_start, stop):
        src_idx = enc_idx + source_offset
        if src_idx < 0 or src_idx >= len(source):
            break
        distances.append((encoded[enc_idx] ^ source[src_idx]).bit_count())
    if not distances:
        return 999.0
    return sum(distances) / len(distances)


def locate_deleted_region(
    source: list[int],
    encoded: list[int],
    *,
    expected_delta: int,
    stride: int = 48,
) -> GapRegion | None:
    """Locate the bounded area that contains all missing output pictures.

    The only model accepted here is ``len(source) > len(encoded)`` with order
    preserved outside one bounded repair area.  We do *not* need to identify
    each individual dropped frame.  Instead we prove two stable facts:

    * before the defect, encoded frame ``i`` matches source frame ``i``;
    * after the defect, encoded frame ``i`` matches source frame
      ``i + expected_delta``.

    This is much more robust than independently guessing the exact offset at
    every sample, especially for anime/static scenes where adjacent dHashes are
    intentionally very similar.  The whole uncertain middle is re-encoded.
    """
    delta = int(expected_delta)
    if delta <= 0 or len(source) - len(encoded) != delta:
        return None
    if len(encoded) < 40 or delta > 5000:
        return None

    sample_stride = max(12, int(stride))
    block_frames = 16
    confidence_margin = 0.75  # average dHash bits/frame between the two hypotheses
    observations: list[tuple[int, float]] = []

    max_start = max(1, len(encoded) - block_frames + 1)
    for enc_start in range(0, max_start, sample_stride):
        prefix_score = _block_alignment_score(
            source, encoded, encoded_start=enc_start, source_offset=0, block_frames=block_frames
        )
        suffix_score = _block_alignment_score(
            source, encoded, encoded_start=enc_start, source_offset=delta, block_frames=block_frames
        )
        # Negative => offset 0 clearly better. Positive => full delta clearly better.
        observations.append((enc_start, prefix_score - suffix_score))

    if len(observations) < 6:
        return None

    # Walk from the start until the prefix hypothesis is no longer sustained.
    left: int | None = None
    non_prefix_run = 0
    prefix_observations = 0
    for frame, preference in observations:
        if preference <= -confidence_margin:
            left = frame
            prefix_observations += 1
            non_prefix_run = 0
        else:
            non_prefix_run += 1
            if left is not None and non_prefix_run >= 3:
                break

    # Walk backwards until the final-delta hypothesis is no longer sustained.
    right: int | None = None
    non_suffix_run = 0
    suffix_observations = 0
    for frame, preference in reversed(observations):
        if preference >= confidence_margin:
            right = frame
            suffix_observations += 1
            non_suffix_run = 0
        else:
            non_suffix_run += 1
            if right is not None and non_suffix_run >= 3:
                break

    if left is None or right is None or prefix_observations < 2 or suffix_observations < 2:
        return None
    if right <= left:
        return None

    # Sparse sampling intentionally only gives an approximate boundary. Expand
    # generously; choose_repair_window() expands again to independently
    # decodable HEVC access points before any bytes are replaced.
    pad = max(96, sample_stride * 3)
    start = max(0, left - pad)
    end = min(len(encoded), right + pad)
    if end <= start:
        return None

    confident = sum(1 for _frame, pref in observations if abs(pref) >= confidence_margin)
    return GapRegion(start, end, delta, confident)


def _annexb_start_codes(mm: mmap.mmap) -> Iterable[tuple[int, int]]:
    """Yield ``(start_offset, nal_header_offset)`` for Annex-B NAL units."""
    pos = 0
    size = len(mm)
    while pos < size:
        found = mm.find(b"\x00\x00\x01", pos)
        if found < 0:
            return
        if found > 0 and mm[found - 1] == 0:
            start = found - 1
        else:
            start = found
        header = found + 3
        if header + 1 < size:
            yield start, header
        pos = header + 2


def inspect_hevc_irap(path: Path) -> tuple[list[IrapPoint], bytes, int]:
    """Return IRAP frame ordinals, initial VPS/SPS/PPS bytes and frame count."""
    points: list[IrapPoint] = []
    parameter_chunks: list[bytes] = []
    seen_ps: set[int] = set()
    frame_index = -1

    with path.open("rb") as fh:
        with mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as mm:
            starts = list(_annexb_start_codes(mm))
            for idx, (start, header) in enumerate(starts):
                nal_type = (mm[header] >> 1) & 0x3F
                end = starts[idx + 1][0] if idx + 1 < len(starts) else len(mm)
                if nal_type in _PARAMETER_SET_TYPES and nal_type not in seen_ps:
                    parameter_chunks.append(bytes(mm[start:end]))
                    seen_ps.add(nal_type)
                if nal_type <= 31:
                    payload = header + 2
                    if payload < len(mm) and (mm[payload] & 0x80):
                        frame_index += 1
                        if nal_type in _IRAP_TYPES:
                            points.append(IrapPoint(frame_index, start, nal_type))
    return points, b"".join(parameter_chunks), frame_index + 1


def choose_repair_window(
    *,
    region: GapRegion,
    irap_points: list[IrapPoint],
    encoded_frames: int,
    encoded_size: int,
    bframe_margin: int = 16,
) -> RepairWindow | None:
    before_limit = max(0, region.encoded_start - bframe_margin)
    after_limit = min(encoded_frames, region.encoded_end + bframe_margin)

    before = [p for p in irap_points if p.frame_index <= before_limit]
    after = [p for p in irap_points if p.frame_index >= after_limit]

    if before:
        start_point = before[-1]
        enc_start = start_point.frame_index
        prefix_end = start_point.byte_offset
    else:
        enc_start = 0
        prefix_end = 0

    if after:
        # Prefer IDR/BLA over CRA. CRA is allowed only as a candidate; the full
        # decoder + boundary-fingerprint verification below must then prove it.
        strong = [p for p in after if p.is_strong_boundary]
        end_point = strong[0] if strong else after[0]
        enc_end = end_point.frame_index
        suffix_start = end_point.byte_offset
        strong_suffix = end_point.is_strong_boundary
    else:
        enc_end = encoded_frames
        suffix_start = encoded_size
        strong_suffix = True

    if enc_end <= enc_start:
        return None

    source_start = enc_start
    source_end = enc_end + region.delta
    return RepairWindow(
        encoded_start=enc_start,
        encoded_end=enc_end,
        source_start=source_start,
        source_end=source_end,
        prefix_byte_end=prefix_end,
        suffix_byte_start=suffix_start,
        suffix_is_strong_boundary=strong_suffix,
    )


def _extract_simple_vf(vf_args: list) -> str | None:
    if "-filter_complex" in vf_args:
        return None
    try:
        idx = vf_args.index("-vf")
        return str(vf_args[idx + 1])
    except (ValueError, IndexError):
        return ""


def _replace_simple_vf(command: list, chain: str) -> list:
    cmd = list(command)
    try:
        idx = cmd.index("-vf")
        cmd[idx + 1] = chain
    except ValueError:
        insert_at = cmd.index("-an") if "-an" in cmd else len(cmd) - 1
        cmd[insert_at:insert_at] = ["-vf", chain]
    return cmd


def _force_closed_gop_headers(command: list) -> list:
    cmd = list(command)
    if "libx265" not in cmd:
        return cmd
    extra = "open-gop=0:repeat-headers=1"
    if "-x265-params" in cmd:
        idx = cmd.index("-x265-params")
        existing = str(cmd[idx + 1])
        cmd[idx + 1] = f"{existing}:{extra}" if existing else extra
    else:
        idx = cmd.index("-an") if "-an" in cmd else len(cmd) - 1
        cmd[idx:idx] = ["-x265-params", extra]
    return cmd


def _join_hash_distance(reference: list[int], candidate: list[int], center: int, radius: int = 24) -> float:
    lo = max(0, center - radius)
    hi = min(len(reference), len(candidate), center + radius)
    if hi <= lo:
        return 999.0
    scores = [(reference[i] ^ candidate[i]).bit_count() for i in range(lo, hi)]
    return sum(scores) / len(scores)


class DVPartialFrameRepair:
    def __init__(
        self,
        *,
        tools,
        encoder_config,
        progress_runner,
        log: Callable[[str, str], None],
        verbose_log: Callable[[str], None],
    ) -> None:
        self._tools = tools
        self._encoder_config = encoder_config
        self._progress_runner = progress_runner
        self._log = log
        self._vlog = verbose_log

    def _fingerprint_command(self, *, input_path: str, output_path: Path, source_vf: str = "") -> list:
        fp = f"scale={_FINGERPRINT_WIDTH}:{_FINGERPRINT_HEIGHT}:flags=area,format=gray"
        chain = f"{source_vf},{fp}" if source_vf else fp
        return [
            self._tools.ffmpeg, "-y", "-nostdin", "-v", "error",
            "-i", input_path,
            "-map", "0:v:0", "-vf", chain,
            "-an", "-sn", "-dn", "-fps_mode", "passthrough",
            "-pix_fmt", "gray", "-f", "rawvideo", str(output_path),
        ]

    def _write_fingerprint(self, runner, *, input_path: str, output_path: Path, source_vf: str = "") -> bool:
        output_path.unlink(missing_ok=True)
        rc = runner.run(
            self._fingerprint_command(input_path=input_path, output_path=output_path, source_vf=source_vf),
            allow_error=True,
            timeout=_TIMEOUT_ENCODE(),
            label="DV Partial-Recovery Frame-Fingerprints",
        )
        return rc == 0 and output_path.exists() and output_path.stat().st_size > 0

    def attempt(
        self,
        *,
        state,
        runner,
        expected_rpu_frames: int,
        actual_encode_frames: int,
    ) -> bool:
        req, files = state.request, state.files
        delta = int(expected_rpu_frames) - int(actual_encode_frames)
        encoder_name = str(self._encoder_config.options.get("encoder", "cpu") or "cpu").lower()
        if req.profile_major not in {5, 7, 8} or delta <= 0:
            return False
        if encoder_name != "cpu" or str(self._encoder_config.codec).lower() not in {"h265", "hevc", "x265"}:
            self._vlog("[DV][PARTIAL-RECOVERY] Nur CPU/libx265 ist für HEVC-Splicing freigegeben.")
            return False
        if delta > 5000:
            self._vlog(f"[DV][PARTIAL-RECOVERY] Delta {delta} ist zu groß für eine sichere Teilreparatur.")
            return False

        vf_args = list(state.effective_vf_args or req.vf_args)
        # Build the exact production filter chain first.  Fingerprinting the MKV
        # after this chain makes source-vs-encode alignment valid for P5 as well:
        # the source hash then sees the same libplacebo ICtCp -> HDR10 conversion
        # that created ``encoded.hevc``.  P7/P8 likewise include the exact DV
        # colorspace/setparams normalization used by the normal encode.
        fingerprint_plan = build_dv_encode_command(
            ffmpeg_path=self._tools.ffmpeg,
            encoder_config=self._encoder_config,
            input_path=req.input_path,
            p8_hevc=None,
            output_hevc=files.root / "_unused_partial_probe.hevc",
            vf_args=vf_args,
            profile_major=req.profile_major,
        )
        source_vf = _extract_simple_vf(fingerprint_plan.command)
        if source_vf is None:
            self._vlog(
                "[DV][PARTIAL-RECOVERY] filter_complex aktiv; Teilreparatur wird sicherheitshalber übersprungen."
            )
            return False

        root = files.root
        src_fp = root / "frame_repair_source.gray"
        enc_fp = root / "frame_repair_encoded.gray"
        candidate_fp = root / "frame_repair_candidate.gray"
        replacement = root / "encoded_repair_segment.hevc"
        candidate = root / "encoded_partial_repair.hevc"

        self._log(
            f"⚠️ [DV][PARTIAL-RECOVERY] Suche lokal nach den {delta} fehlenden Bildern, "
            "und versuche ausschließlich diesen Bereich neu zu encodieren.",
            "warn",
        )
        if not self._write_fingerprint(runner, input_path=req.input_path, output_path=src_fp, source_vf=source_vf):
            return False
        if not self._write_fingerprint(runner, input_path=str(files.enc_hevc), output_path=enc_fp):
            return False

        source_hashes = read_dhash_file(src_fp)
        encoded_hashes = read_dhash_file(enc_fp)
        if len(source_hashes) != int(expected_rpu_frames) or len(encoded_hashes) != int(actual_encode_frames):
            self._vlog(
                "[DV][PARTIAL-RECOVERY] Fingerprint-Bildzahlen stimmen nicht mit RPU/Encode-Evidenz überein: "
                f"source={len(source_hashes)}, encoded={len(encoded_hashes)}."
            )
            return False

        region = locate_deleted_region(source_hashes, encoded_hashes, expected_delta=delta)
        if region is None:
            self._vlog("[DV][PARTIAL-RECOVERY] Fehlbereich konnte nicht eindeutig als reine Bildlöschung lokalisiert werden.")
            return False

        try:
            iraps, parameter_sets, parsed_frames = inspect_hevc_irap(files.enc_hevc)
            encoded_size = files.enc_hevc.stat().st_size
        except (OSError, ValueError) as exc:
            self._vlog(f"[DV][PARTIAL-RECOVERY] HEVC-IRAP-Analyse fehlgeschlagen: {exc}")
            return False
        if parsed_frames != int(actual_encode_frames):
            self._vlog(
                f"[DV][PARTIAL-RECOVERY] HEVC-Parser zählt {parsed_frames} statt {actual_encode_frames} Bilder; kein Raw-Splice."
            )
            return False

        window = choose_repair_window(
            region=region,
            irap_points=iraps,
            encoded_frames=actual_encode_frames,
            encoded_size=encoded_size,
            bframe_margin=max(16, int(self._encoder_config.options.get("bf", 0) or 0) * 2),
        )
        if window is None or window.source_end > expected_rpu_frames:
            return False

        # Build the same normal encode, then constrain it to the source-frame
        # interval after all visual filters (including P5 libplacebo conversion
        # and subtitle burn-in) have seen original timestamps.
        plan = build_dv_encode_command(
            ffmpeg_path=self._tools.ffmpeg,
            encoder_config=self._encoder_config,
            input_path=req.input_path,
            p8_hevc=None,
            output_hevc=replacement,
            vf_args=vf_args,
            profile_major=req.profile_major,
        )
        processed_vf = _extract_simple_vf(plan.command)
        if processed_vf is None:
            return False
        trim = (
            f"trim=start_frame={window.source_start}:end_frame={window.source_end},"
            "setpts=PTS-STARTPTS"
        )
        segment_cmd = _replace_simple_vf(plan.command, f"{processed_vf},{trim}" if processed_vf else trim)
        segment_cmd = _force_closed_gop_headers(segment_cmd)
        self._vlog(
            "[DV][PARTIAL-RECOVERY] Reparaturfenster: "
            f"Encode {window.encoded_start}..{window.encoded_end}, "
            f"Quelle {window.source_start}..{window.source_end} "
            f"({window.replacement_frames} Bilder), suffix={'IDR/BLA' if window.suffix_is_strong_boundary else 'CRA'}"
        )
        self._vlog(f"[DV][PARTIAL-RECOVERY CMD] {_cmd_str(segment_cmd)}")

        replacement.unlink(missing_ok=True)
        dur_ms = self._progress_runner.probe_ms(req.input_path)
        rc = self._progress_runner.run_p(
            segment_cmd,
            req.input_path,
            dur_ms,
            timeout_s=_TIMEOUT_ENCODE(),
            label="[DV][PARTIAL-RECOVERY] Bereich neu encodieren",
        )
        if rc != 0 or not replacement.exists() or replacement.stat().st_size <= 0:
            return False
        segment_frames = self._progress_runner.take_output_frame_count(req.input_path, process_rc=rc)
        if segment_frames != window.replacement_frames:
            self._vlog(
                f"[DV][PARTIAL-RECOVERY] Segment hat {segment_frames} statt {window.replacement_frames} Bilder."
            )
            return False

        # Raw HEVC concatenation is only a *candidate*.  Duplicate headers and
        # sequence-end markers are legal between independent sequences.  The
        # candidate is never committed until full decoder + timeline checks pass.
        candidate.unlink(missing_ok=True)
        try:
            with files.enc_hevc.open("rb") as old, candidate.open("wb") as out:
                remaining = window.prefix_byte_end
                while remaining > 0:
                    chunk = old.read(min(4 * 1024 * 1024, remaining))
                    if not chunk:
                        return False
                    out.write(chunk)
                    remaining -= len(chunk)
                with replacement.open("rb") as rep:
                    while chunk := rep.read(4 * 1024 * 1024):
                        out.write(chunk)
                if parameter_sets and window.suffix_byte_start < encoded_size:
                    out.write(parameter_sets)
                old.seek(window.suffix_byte_start)
                while chunk := old.read(4 * 1024 * 1024):
                    out.write(chunk)
        except OSError as exc:
            self._vlog(f"[DV][PARTIAL-RECOVERY] Kandidat konnte nicht zusammengesetzt werden: {exc}")
            return False

        # Producing the candidate fingerprint is also a full decoder pass.
        if not self._write_fingerprint(runner, input_path=str(candidate), output_path=candidate_fp):
            self._vlog("[DV][PARTIAL-RECOVERY] Zusammengesetzter HEVC-Kandidat ist nicht vollständig decodierbar.")
            return False
        candidate_hashes = read_dhash_file(candidate_fp)
        if len(candidate_hashes) != int(expected_rpu_frames):
            self._vlog(
                f"[DV][PARTIAL-RECOVERY] Kandidat hat {len(candidate_hashes)} statt {expected_rpu_frames} decodierbare Bilder."
            )
            return False

        left_distance = _join_hash_distance(source_hashes, candidate_hashes, window.source_start)
        right_distance = _join_hash_distance(source_hashes, candidate_hashes, window.source_end)
        if left_distance > 18.0 or right_distance > 18.0:
            self._vlog(
                "[DV][PARTIAL-RECOVERY] Übergangsvergleich nicht eindeutig genug: "
                f"links={left_distance:.2f}, rechts={right_distance:.2f} dHash-Bits."
            )
            return False

        previous = root / "encoded_frame_mismatch.hevc"
        previous.unlink(missing_ok=True)
        try:
            files.enc_hevc.replace(previous)
            candidate.replace(files.enc_hevc)
        except OSError:
            if not files.enc_hevc.exists() and previous.exists():
                previous.replace(files.enc_hevc)
            return False

        state.frame_recovery_applied = True
        state.frame_recovery_original_count = int(actual_encode_frames)
        state.frame_recovery_final_count = int(expected_rpu_frames)
        state.frame_recovery_message = (
            f"Teilreparatur: Frames {window.source_start}..{window.source_end} "
            "aus Original-MKV neu encodiert und vollständig validiert."
        )
        self._log(
            "✅ [DV][PARTIAL-RECOVERY] Nur der lokalisierte Fehlerbereich wurde neu encodiert; "
            f"finale Bildzahl={expected_rpu_frames}. Der Erstencode bleibt als {previous.name} erhalten.",
            "info",
        )
        return True
