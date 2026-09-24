from __future__ import annotations

import math
import subprocess
import sys
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
    histogram: tuple[float, ...]


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


def _scaled_dimensions(probe: VideoProbe, analysis_width: int) -> tuple[int, int]:
    source_w = max(2, int(probe.width or 1920))
    source_h = max(2, int(probe.height or 1080))
    width = max(64, min(source_w, int(analysis_width)))
    width -= width % 2
    height = max(2, round(source_h * width / source_w))
    height -= height % 2
    return width, height


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


def _histogram(values: np.ndarray, bins: int) -> tuple[float, ...]:
    # Histogram in PQ code domain is much more stable for scene-cut detection
    # than a linear-nits histogram dominated by the dark end of HDR pictures.
    hist, _ = np.histogram(values, bins=max(16, int(bins)), range=(0.0, 1.0))
    total = float(hist.sum()) or 1.0
    return tuple((hist.astype(np.float64) / total).tolist())


def scan_pq_video(
    path: str | Path,
    probe: VideoProbe,
    *,
    ffmpeg: str = "ffmpeg",
    analysis_width: int = 256,
    histogram_bins: int = 64,
    progress_interval_s: float = 2.0,
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
    last_progress = time.monotonic()
    expected = probe.frames or 0
    try:
        while True:
            raw = _read_exact(proc.stdout, frame_bytes)
            if not raw:
                break
            if len(raw) != frame_bytes:
                raise RuntimeError(
                    f"TRUNCATED_RAW_FRAME: expected {frame_bytes} bytes, got {len(raw)}"
                )

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
                if expected > 0:
                    pct = min(100.0, current * 100.0 / expected)
                    print(f"HDR10+ scan: {current}/{expected} frames ({pct:.1f}%)", file=sys.stderr, flush=True)
                else:
                    print(f"HDR10+ scan: {current} frames", file=sys.stderr, flush=True)
                last_progress = now

        stderr = proc.stderr.read().decode("utf-8", errors="replace").strip()
        rc = proc.wait()
        if rc != 0:
            raise RuntimeError(stderr or f"ffmpeg rc={rc}")
    except Exception:
        if proc.poll() is None:
            proc.kill()
        try:
            proc.wait(timeout=2)
        except Exception:
            pass
        raise

    if not results:
        raise RuntimeError("NO_DECODED_FRAMES")
    return ScanResult(tuple(results), width, height)


__all__ = ["FrameStatistics", "ScanResult", "scan_pq_video"]
