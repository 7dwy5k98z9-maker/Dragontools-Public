from __future__ import annotations

from array import array
import math
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

from .decoder import VideoProbe

# SMPTE ST 2084 constants. Input RGB code values are normalized PQ samples.
_M1 = 2610.0 / 16384.0
_M2 = 2523.0 / 32.0
_C1 = 3424.0 / 4096.0
_C2 = 2413.0 / 128.0
_C3 = 2392.0 / 128.0
_PEAK_NITS = 10000.0


@dataclass(frozen=True, slots=True)
class FrameStatistics:
    index: int
    max_scl_nits: tuple[float, float, float]
    average_maxrgb_nits: float
    p01_nits: float
    p25_nits: float
    p50_nits: float
    p75_nits: float
    p90_nits: float
    p95_nits: float
    p9998_nits: float
    p9999_nits: float
    below_100_nits_percent: float
    # Compact uint32 bin counts. ``histogram_distance`` normalizes both
    # inputs itself, therefore per-frame Python float tuples are unnecessary.
    # This removes the dominant O(frame_count * bins) Python-object overhead.
    histogram: tuple[float, ...] | array


@dataclass(frozen=True, slots=True)
class ScanResult:
    frames: tuple[FrameStatistics, ...]
    width: int
    height: int


def _pq_eotf_array(code: np.ndarray) -> np.ndarray:
    x = np.clip(code.astype(np.float32, copy=False), 0.0, 1.0)
    p = np.power(x, 1.0 / _M2, dtype=np.float32)
    numerator = np.maximum(p - _C1, 0.0)
    denominator = np.maximum(_C2 - _C3 * p, np.finfo(np.float32).tiny)
    return (_PEAK_NITS * np.power(numerator / denominator, 1.0 / _M1, dtype=np.float32)).astype(
        np.float32, copy=False
    )


class FFmpegInactivityTimeoutError(RuntimeError):
    """FFmpeg stopped producing decoded frames for too long."""


def _scaled_dimensions(probe: VideoProbe, analysis_width: int) -> tuple[int, int]:
    if probe.width is None or probe.height is None or probe.width <= 0 or probe.height <= 0:
        raise ValueError("PROBE_DIMENSIONS_MISSING")
    source_w = max(2, int(probe.width))
    source_h = max(2, int(probe.height))
    width = max(64, min(source_w, int(analysis_width)))
    width -= width % 2
    height = max(2, round(source_h * width / source_w))
    height -= height % 2
    return width, height



def _format_duration(seconds: float) -> str:
    value = max(0, int(round(float(seconds))))
    hours, remainder = divmod(value, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"

def _read_exact(stream, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _put_until_stopped(target: queue.Queue, item, stop: threading.Event) -> bool:
    while not stop.is_set():
        try:
            target.put(item, timeout=0.1)
            return True
        except queue.Full:
            continue
    return False


def _start_frame_reader(stream, frame_bytes: int, stop: threading.Event):
    frame_queue: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=2)

    def _reader() -> None:
        try:
            while not stop.is_set():
                raw = _read_exact(stream, frame_bytes)
                if not raw:
                    _put_until_stopped(frame_queue, ("eof", b""), stop)
                    return
                if not _put_until_stopped(frame_queue, ("frame", raw), stop):
                    return
                if len(raw) != frame_bytes:
                    _put_until_stopped(frame_queue, ("eof", b""), stop)
                    return
        except (OSError, ValueError) as exc:
            _put_until_stopped(frame_queue, ("error", exc), stop)

    thread = threading.Thread(target=_reader, name="hdr10plus-frame-reader", daemon=True)
    thread.start()
    return frame_queue, thread


def _start_stderr_reader(stream, stop: threading.Event, *, limit: int = 256 * 1024):
    chunks: list[bytes] = []
    size = 0

    def _reader() -> None:
        nonlocal size
        try:
            while not stop.is_set():
                chunk = stream.read(65536)
                if not chunk:
                    return
                chunks.append(chunk)
                size += len(chunk)
                while size > limit and chunks:
                    removed = chunks.pop(0)
                    size -= len(removed)
        except (OSError, ValueError):
            return

    thread = threading.Thread(target=_reader, name="hdr10plus-stderr-reader", daemon=True)
    thread.start()

    def _text() -> str:
        return b"".join(chunks).decode("utf-8", errors="replace").strip()

    return thread, _text


def _histogram(values: np.ndarray, bins: int) -> array:
    # Histogram in PQ code domain is much more stable for scene-cut detection
    # than a linear-nits histogram dominated by the dark end of HDR pictures.
    # Store raw uint32 bin counts instead of a tuple of Python floats. The
    # distance function normalizes both histograms, so the mathematical result
    # is identical while feature-length scans need far less RAM.
    hist, _ = np.histogram(values, bins=max(16, int(bins)), range=(0.0, 1.0))
    return array("I", (int(value) for value in hist))


def _progress_message(
    *,
    current: int,
    expected: int,
    reliability: str,
    fps: float,
    elapsed: float,
) -> str:
    if expected > 0 and current <= expected:
        pct = min(100.0, current * 100.0 / expected)
        remaining = max(0, expected - current)
        eta_s = remaining / fps if fps > 0 else 0.0
        reliability_key = str(reliability or "")
        suffix = " (geschätzt)" if reliability_key == "estimated" else (" (Metadaten)" if reliability_key == "reported" else "")
        return (
            f"HDR10+ scan: {current}/{expected} frames ({pct:.1f}%{suffix}) | "
            f"{fps:.1f} fps | elapsed {_format_duration(elapsed)} | "
            f"ETA {_format_duration(eta_s)}{suffix}"
        )
    note = " | Gesamtschätzung überschritten" if expected > 0 and current > expected else ""
    return f"HDR10+ scan: {current} frames | {fps:.1f} fps | elapsed {_format_duration(elapsed)}{note}"


def scan_pq_video(
    path: str | Path,
    probe: VideoProbe,
    *,
    ffmpeg: str = "ffmpeg",
    analysis_width: int = 256,
    histogram_bins: int = 64,
    progress_interval_s: float = 2.0,
    inactivity_timeout_s: int | float | None = 300,
) -> ScanResult:
    """Decode every presentation frame to a small PQ RGB analysis surface.

    The video is spatially reduced only for metadata analysis; temporal sampling
    is never reduced. This preserves exact frame count / scene alignment while
    keeping CPU and pipe bandwidth practical for feature-length sources.
    """
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)

    width, height = _scaled_dimensions(probe, analysis_width)
    pixels = width * height
    frame_bytes = pixels * 3 * 2  # gbrp16le: three planar uint16 components
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel", "error",
        "-i", str(source),
        "-map", "0:v:0",
        "-an", "-sn", "-dn",
        "-vf", f"scale={width}:{height}:flags=bilinear,format=gbrp16le",
        "-pix_fmt", "gbrp16le",
        "-fps_mode", "passthrough",
        "-f", "rawvideo",
        "pipe:1",
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        bufsize=0,
    )
    if proc.stdout is None or proc.stderr is None:
        proc.kill()
        raise RuntimeError("FFMPEG_PIPE_FAILED")

    results: list[FrameStatistics] = []
    scan_started = time.monotonic()
    last_progress = scan_started
    last_frame_activity = last_progress
    expected = (probe.frames or 0) if str(getattr(probe, "frame_count_reliability", "unknown") or "unknown") != "unknown" else 0
    stop = threading.Event()
    frame_queue, frame_thread = _start_frame_reader(proc.stdout, frame_bytes, stop)
    stderr_thread, stderr_text = _start_stderr_reader(proc.stderr, stop)
    try:
        while True:
            try:
                kind, payload = frame_queue.get(timeout=0.25)
            except queue.Empty:
                if (
                    inactivity_timeout_s is not None
                    and time.monotonic() - last_frame_activity >= max(0.1, float(inactivity_timeout_s))
                ):
                    raise FFmpegInactivityTimeoutError(
                        f"FFMPEG_INACTIVITY_TIMEOUT after {inactivity_timeout_s}s"
                    )
                if proc.poll() is not None and not frame_thread.is_alive():
                    break
                continue

            if kind == "eof":
                break
            if kind == "error":
                raise RuntimeError(f"FFMPEG_PIPE_READ_FAILED: {payload}")

            raw = payload
            if not isinstance(raw, (bytes, bytearray)):
                raise RuntimeError("FFMPEG_PIPE_PROTOCOL_ERROR")
            if len(raw) != frame_bytes:
                raise RuntimeError(
                    f"TRUNCATED_RAW_FRAME: expected {frame_bytes} bytes, got {len(raw)}"
                )
            last_frame_activity = time.monotonic()

            planes = np.frombuffer(raw, dtype="<u2", count=pixels * 3).reshape(3, pixels)
            # gbrp16le plane order is G, B, R. RGB code values are normalized PQ.
            g_code = planes[0].astype(np.float32) / 65535.0
            b_code = planes[1].astype(np.float32) / 65535.0
            r_code = planes[2].astype(np.float32) / 65535.0

            r_nits = _pq_eotf_array(r_code)
            g_nits = _pq_eotf_array(g_code)
            b_nits = _pq_eotf_array(b_code)
            maxrgb = np.maximum(np.maximum(r_nits, g_nits), b_nits)
            maxrgb_code = np.maximum(np.maximum(r_code, g_code), b_code)

            # HDR10+ metadata percentiles operate on linearized maxRGB.
            qs = np.percentile(
                maxrgb,
                [1.0, 25.0, 50.0, 75.0, 90.0, 95.0, 99.98, 99.99],
                method="linear",
            )
            results.append(
                FrameStatistics(
                    index=len(results),
                    max_scl_nits=(float(r_nits.max()), float(g_nits.max()), float(b_nits.max())),
                    average_maxrgb_nits=float(maxrgb.mean(dtype=np.float64)),
                    p01_nits=float(qs[0]),
                    p25_nits=float(qs[1]),
                    p50_nits=float(qs[2]),
                    p75_nits=float(qs[3]),
                    p90_nits=float(qs[4]),
                    p95_nits=float(qs[5]),
                    p9998_nits=float(qs[6]),
                    p9999_nits=float(qs[7]),
                    below_100_nits_percent=float(np.count_nonzero(maxrgb <= 100.0) * 100.0 / pixels),
                    histogram=_histogram(maxrgb_code, histogram_bins),
                )
            )

            now = time.monotonic()
            if now - last_progress >= max(0.25, float(progress_interval_s)):
                current = len(results)
                elapsed = max(0.001, now - scan_started)
                fps = current / elapsed
                print(
                    _progress_message(
                        current=current,
                        expected=expected,
                        reliability=str(getattr(probe, "frame_count_reliability", "unknown") or "unknown"),
                        fps=fps,
                        elapsed=elapsed,
                    ),
                    file=sys.stderr,
                    flush=True,
                )
                last_progress = now

        try:
            rc = proc.wait(
                timeout=None
                if inactivity_timeout_s is None
                else max(0.1, float(inactivity_timeout_s))
            )
        except subprocess.TimeoutExpired as exc:
            raise FFmpegInactivityTimeoutError(
                f"FFMPEG_INACTIVITY_TIMEOUT after {inactivity_timeout_s}s while waiting for exit"
            ) from exc
        stderr_thread.join(timeout=2.0)
        if rc != 0:
            raise RuntimeError(stderr_text() or f"ffmpeg rc={rc}")
    except Exception:
        stop.set()
        if proc.poll() is None:
            proc.kill()
        try:
            proc.wait(timeout=2)
        except (subprocess.TimeoutExpired, OSError):
            pass
        raise
    finally:
        stop.set()
        for stream in (proc.stdout, proc.stderr):
            try:
                stream.close()
            except (OSError, ValueError):
                pass
        frame_thread.join(timeout=1.0)
        stderr_thread.join(timeout=1.0)

    if not results:
        raise RuntimeError("NO_DECODED_FRAMES")
    return ScanResult(tuple(results), width, height)


__all__ = ["FFmpegInactivityTimeoutError", "FrameStatistics", "ScanResult", "_progress_message", "scan_pq_video"]
