# -*- coding: utf-8 -*-
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

try:
    import cv2 as _cv2
    import numpy as _np
except Exception:  # pragma: no cover - optional build dependency
    _cv2 = None
    _np = None

from .audio_video_match_models import AudioVideoMatcherSettings, FrameSignature, MatchPoint
from .audio_video_match_utils import _clamp
from .process_runner import subprocess_no_window_kwargs

RunBytesFn = Callable[[list[str], int | float | None], bytes]

def opencv_available() -> bool:
    return _cv2 is not None and _np is not None


def image_analysis_backend_label() -> str:
    if opencv_available():
        version = str(getattr(_cv2, "__version__", "") or "").strip()
        return f"OpenCV {version}".strip()
    return "FFmpeg/dHash-Fallback"

def _default_run_bytes(cmd: list[str], timeout_s: int | float | None) -> bytes:
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        timeout=timeout_s,
        check=False,
        **subprocess_no_window_kwargs(),
    )
    if result.returncode != 0:
        detail = (result.stderr or b"").decode("utf-8", errors="replace").strip()
        raise RuntimeError(detail or f"{Path(cmd[0]).name} fehlgeschlagen")
    return result.stdout or b""


class FrameExtractor:
    def __init__(
        self,
        ffmpeg_path: str,
        *,
        settings: AudioVideoMatcherSettings | None = None,
        run_bytes: RunBytesFn | None = None,
    ) -> None:
        self.ffmpeg_path = str(ffmpeg_path)
        self.settings = settings or AudioVideoMatcherSettings()
        self._run_bytes = run_bytes or _default_run_bytes

    def extract_window_signatures(
        self,
        path: str,
        start_s: float,
        duration_s: float,
        *,
        fps: float | None = None,
    ) -> list[FrameSignature]:
        width = int(self.settings.analysis_width)
        height = int(self.settings.analysis_height)
        fps_value = max(0.5, float(fps or self.settings.coarse_fps))
        duration = max(0.20, float(duration_s))
        start = max(0.0, float(start_s))
        vf = (
            f"fps={fps_value:.3f},"
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
            "format=gray"
        )
        cmd = [
            self.ffmpeg_path,
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            "-ss",
            f"{start:.3f}",
            "-i",
            path,
            "-t",
            f"{duration:.3f}",
            "-map",
            "0:v:0",
            "-an",
            "-sn",
            "-dn",
            "-vf",
            vf,
            "-f",
            "rawvideo",
            "pipe:1",
        ]
        timeout = max(20.0, duration * 8.0)
        raw = self._run_bytes(cmd, timeout)
        frame_size = width * height
        signatures: list[FrameSignature] = []
        if frame_size <= 0:
            return signatures
        frame_count = len(raw) // frame_size
        for idx in range(frame_count):
            frame = raw[idx * frame_size:(idx + 1) * frame_size]
            if len(frame) != frame_size:
                continue
            time_s = start + idx / fps_value
            signatures.append(_signature_from_gray_frame(frame, width, height, time_s))
        return signatures


def _content_box(frame: bytes, width: int, height: int) -> tuple[int, int, int, int]:
    threshold = 10
    rows: list[int] = []
    for y in range(height):
        row = frame[y * width:(y + 1) * width]
        if row and sum(row) / len(row) > threshold:
            rows.append(y)
    cols: list[int] = []
    for x in range(width):
        total = 0
        for y in range(height):
            total += frame[y * width + x]
        if total / max(height, 1) > threshold:
            cols.append(x)
    if not rows or not cols:
        return 0, 0, width, height
    left, right = min(cols), max(cols) + 1
    top, bottom = min(rows), max(rows) + 1
    if (right - left) < width * 0.35 or (bottom - top) < height * 0.35:
        return 0, 0, width, height
    return left, top, right, bottom


def _sample_grid(frame: bytes, width: int, height: int, box: tuple[int, int, int, int], gw: int, gh: int) -> list[int]:
    left, top, right, bottom = box
    bw = max(1, right - left)
    bh = max(1, bottom - top)
    values: list[int] = []
    for gy in range(gh):
        y0 = int(top + gy * bh / gh)
        y1 = int(top + (gy + 1) * bh / gh)
        y1 = max(y0 + 1, min(bottom, y1))
        for gx in range(gw):
            x0 = int(left + gx * bw / gw)
            x1 = int(left + (gx + 1) * bw / gw)
            x1 = max(x0 + 1, min(right, x1))
            total = 0
            count = 0
            for y in range(y0, y1):
                offset = y * width
                for x in range(x0, x1):
                    total += frame[offset + x]
                    count += 1
            values.append(int(total / max(count, 1)))
    return values


def _signature_from_gray_frame(frame: bytes, width: int, height: int, time_s: float) -> FrameSignature:
    if opencv_available():
        signature = _signature_from_gray_frame_opencv(frame, width, height, time_s)
        if signature is not None:
            return signature
    return _signature_from_gray_frame_python(frame, width, height, time_s)


def _signature_from_gray_frame_python(frame: bytes, width: int, height: int, time_s: float) -> FrameSignature:
    box = _content_box(frame, width, height)
    grid = _sample_grid(frame, width, height, box, 17, 16)
    dhash = 0
    bits = 0
    for y in range(16):
        row = y * 17
        for x in range(16):
            if grid[row + x] > grid[row + x + 1]:
                dhash |= 1 << bits
            bits += 1
    sample = _sample_grid(frame, width, height, box, 16, 16)
    avg = sum(sample) / max(len(sample), 1)
    var = sum((p - avg) ** 2 for p in sample) / max(len(sample), 1)
    return FrameSignature(time_s=float(time_s), dhash=dhash, mean_luma=avg, variance=var, bits=bits)


def _opencv_content_box(gray) -> tuple[int, int, int, int]:
    if gray.size <= 0:
        return 0, 0, 1, 1
    mask = gray > 10
    rows = _np.where(mask.mean(axis=1) > 0.03)[0]
    cols = _np.where(mask.mean(axis=0) > 0.03)[0]
    height, width = gray.shape[:2]
    if rows.size == 0 or cols.size == 0:
        return 0, 0, width, height
    left, right = int(cols[0]), int(cols[-1]) + 1
    top, bottom = int(rows[0]), int(rows[-1]) + 1
    if (right - left) < width * 0.35 or (bottom - top) < height * 0.35:
        return 0, 0, width, height
    return left, top, right, bottom


def _hash_adjacent_grid(grid) -> tuple[int, int]:
    hsh = 0
    bits = 0
    height, width = grid.shape[:2]
    for y in range(height):
        for x in range(max(0, width - 1)):
            if int(grid[y, x]) > int(grid[y, x + 1]):
                hsh |= 1 << bits
            bits += 1
    return hsh, bits


def _signature_from_gray_frame_opencv(frame: bytes, width: int, height: int, time_s: float) -> FrameSignature | None:
    try:
        gray = _np.frombuffer(frame, dtype=_np.uint8).reshape((height, width))
        left, top, right, bottom = _opencv_content_box(gray)
        cropped = gray[top:bottom, left:right]
        if cropped.size <= 0:
            cropped = gray

        luma_grid = _cv2.resize(cropped, (17, 16), interpolation=_cv2.INTER_AREA)
        dhash, bits = _hash_adjacent_grid(luma_grid)

        sample = _cv2.resize(cropped, (16, 16), interpolation=_cv2.INTER_AREA)
        avg = float(sample.mean())
        var = float(sample.var())

        blurred = _cv2.GaussianBlur(cropped, (3, 3), 0)
        edges = _cv2.Canny(blurred, 50, 150)
        edge_grid = _cv2.resize(edges, (17, 16), interpolation=_cv2.INTER_AREA)
        edge_hash, edge_bits = _hash_adjacent_grid(edge_grid)
        edge_density = float((edges > 0).mean())

        return FrameSignature(
            time_s=float(time_s),
            dhash=dhash,
            mean_luma=avg,
            variance=var,
            bits=bits,
            edge_hash=edge_hash,
            edge_bits=edge_bits,
            edge_density=edge_density,
            backend="opencv",
        )
    except Exception:
        return None


def frame_similarity(a: FrameSignature, b: FrameSignature) -> float:
    bits = max(a.bits, b.bits, 1)
    hamming = (a.dhash ^ b.dhash).bit_count()
    hash_similarity = 1.0 - hamming / bits
    mean_similarity = 1.0 - min(abs(a.mean_luma - b.mean_luma) / 96.0, 1.0)
    edge_similarity = 0.0
    texture_similarity = 0.0
    edge_weight = 0.0
    if a.edge_bits and b.edge_bits:
        edge_bits = max(a.edge_bits, b.edge_bits, 1)
        edge_hamming = (a.edge_hash ^ b.edge_hash).bit_count()
        edge_similarity = 1.0 - edge_hamming / edge_bits
        texture_similarity = 1.0 - min(abs(a.edge_density - b.edge_density) / 0.30, 1.0)
        edge_weight = 0.22
    variance_penalty = 1.0
    if a.variance < 20.0 or b.variance < 20.0:
        variance_penalty = 0.90
    if edge_weight:
        score = (
            hash_similarity * 0.58
            + mean_similarity * 0.10
            + edge_similarity * 0.24
            + texture_similarity * 0.08
        )
    else:
        score = hash_similarity * 0.88 + mean_similarity * 0.12
    return _clamp(score * variance_penalty, 0.0, 1.0)


class FrameMatcher:
    def __init__(self, extractor: FrameExtractor, *, settings: AudioVideoMatcherSettings | None = None) -> None:
        self.extractor = extractor
        self.settings = settings or extractor.settings

    def characteristic_signature(self, path: str, center_s: float, duration_s: float) -> FrameSignature | None:
        radius = max(0.5, self.settings.target_probe_radius_s)
        start = max(0.0, center_s - radius)
        end = min(max(start + 0.2, duration_s), center_s + radius)
        signatures = self.extractor.extract_window_signatures(
            path,
            start,
            max(0.2, end - start),
            fps=max(1.0, self.settings.coarse_fps),
        )
        if not signatures:
            return None
        return max(signatures, key=lambda s: (s.variance, s.edge_density, -abs(s.time_s - center_s)))

    def find_match(
        self,
        source_path: str,
        reference: FrameSignature,
        *,
        expected_time_s: float,
        source_duration_s: float,
        search_window_s: float,
    ) -> MatchPoint | None:
        coarse = self._find_best_in_window(
            source_path,
            reference,
            expected_time_s=expected_time_s,
            source_duration_s=source_duration_s,
            search_window_s=search_window_s,
            fps=self.settings.coarse_fps,
        )
        if coarse is None:
            return None
        refined = self._find_best_in_window(
            source_path,
            reference,
            expected_time_s=coarse.matched_time_s,
            source_duration_s=source_duration_s,
            search_window_s=1.25,
            fps=self.settings.refine_fps,
        )
        best = refined or coarse
        if best.similarity < self.settings.min_similarity:
            return None
        return best

    def _find_best_in_window(
        self,
        source_path: str,
        reference: FrameSignature,
        *,
        expected_time_s: float,
        source_duration_s: float,
        search_window_s: float,
        fps: float,
    ) -> MatchPoint | None:
        half = max(0.5, float(search_window_s))
        start = _clamp(expected_time_s - half, 0.0, max(source_duration_s - 0.2, 0.0))
        end = _clamp(expected_time_s + half, start + 0.2, max(source_duration_s, start + 0.2))
        candidates = self.extractor.extract_window_signatures(source_path, start, end - start, fps=fps)
        if not candidates:
            return None
        best_sig = max(candidates, key=lambda sig: frame_similarity(reference, sig))
        sim = frame_similarity(reference, best_sig)
        return MatchPoint(
            reference_time_s=reference.time_s,
            matched_time_s=best_sig.time_s,
            similarity=sim,
            confidence=sim * 100.0,
        )
