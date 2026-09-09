# -*- coding: utf-8 -*-
"""
dragontools/worker/converter_detection.py

Ausgelagerte Erkennungs-Funktionen des ConverterThread:
    - detect_crop         : Auto-Crop via ffmpeg cropdetect
    - detect_imax_auto    : IMAX-Erkennung über wechselnde Aspect-Ratios
"""
from __future__ import annotations

import re
import subprocess
import traceback
from pathlib import Path


from ..core.process_runner import subprocess_no_window_kwargs as _no_window_kwargs


def _safe_int(value, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _sanitize_imax_interval(value) -> int:
    return max(30, min(600, _safe_int(value, 90)))


def _sanitize_autocrop_mode(value) -> str:
    return "multi" if str(value or "").strip().lower() == "multi" else "single"


def _sanitize_autocrop_start(value) -> int:
    return max(0, min(3600, _safe_int(value, 30)))


def _sanitize_autocrop_duration(value) -> int:
    return max(2, min(120, _safe_int(value, 45)))


def _sanitize_autocrop_interval(value) -> int:
    return max(60, min(1800, _safe_int(value, 600)))


def _imax_probe_offsets(duration_s: float, interval_s: int) -> list[int]:
    if duration_s < 60:
        return []
    interval_s = _sanitize_imax_interval(interval_s)
    end = max(0, int(duration_s) - 10)
    if end <= 60:
        return []
    return list(range(60, end, interval_s))


def _autocrop_probe_offsets(duration_s: float | None, *, start_s: int, interval_s: int) -> list[int]:
    start_s = _sanitize_autocrop_start(start_s)
    interval_s = _sanitize_autocrop_interval(interval_s)
    if not duration_s or duration_s <= start_s + 10:
        return [start_s]
    end = max(start_s, int(duration_s) - 10)
    offsets = list(range(start_s, end, interval_s))
    return offsets or [start_s]


def _best_crop_from_output(
    raw: str,
    *,
    source_w: int = 0,
    source_h: int = 0,
) -> tuple[int, int, int, int] | None:
    matches = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", raw or "")
    if not matches:
        if source_w > 0 and source_h > 0:
            return source_w, source_h, 0, 0
        return None

    counts: dict[tuple[int, int, int, int], int] = {}
    for match in matches:
        crop = tuple(int(part) for part in match)
        counts[crop] = counts.get(crop, 0) + 1
    return max(counts, key=lambda crop: (counts[crop], crop[0] * crop[1]))


class ConverterDetectionHelper:
    """Bündelt die Erkennungs-Funktionen (Crop, IMAX)."""

    def __init__(self, worker):
        self.worker = worker

    # ------------------------------------------------------------------
    def detect_crop(
        self,
        path: str,
        w: int,
        h: int,
        mode: str = "single",
        start_s: int = 30,
        probe_duration_s: int = 45,
        interval_s: int = 600,
        duration_s: float | None = None,
    ) -> str | None:
        """
        Cropdetect via ffmpeg. Alignment: mod 2 (Codec-Pflicht).
        NVENC-Alignment auf 32 ist nicht nötig - das conformance-window-Problem
        wird für DV über Level 5 RPU geloest, für Standard-MKV existiert es nicht.
        """
        worker = self.worker
        if not w or not h:
            return None
        mode = _sanitize_autocrop_mode(mode)
        start_s = _sanitize_autocrop_start(start_s)
        probe_duration_s = _sanitize_autocrop_duration(probe_duration_s)
        interval_s = _sanitize_autocrop_interval(interval_s)
        offsets = [start_s]
        if mode == "multi":
            offsets = _autocrop_probe_offsets(
                duration_s,
                start_s=start_s,
                interval_s=interval_s,
            )
        raw_parts: list[str] = []
        try:
            for offset in offsets:
                cmd = [
                    worker.tools.ffmpeg, "-hide_banner", "-ss", str(offset), "-i", path,
                    "-t", str(probe_duration_s), "-vf", "cropdetect=limit=0.08:round=2:reset=1",
                    "-an", "-sn", "-f", "null", "-",
                ]
                r = subprocess.run(
                    cmd, capture_output=True, text=True, encoding="utf-8",
                    errors="replace", **_no_window_kwargs(),
                    timeout=max(20, probe_duration_s + 45),
                )
                raw_parts.append((r.stderr or "") + (r.stdout or ""))
        except Exception as e:
            worker.log(
                f"⚠️ Auto-Crop-Erkennung fehlgeschlagen bei {Path(path).name}: {e}",
                "warn",
            )
            worker.log(traceback.format_exc(), "error")
            return None
        raw = "\n".join(raw_parts)
        matches = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", raw)
        if not matches:
            return None
        c = {}
        for m in matches:
            k = tuple(int(x) for x in m)
            c[k] = c.get(k, 0) + 1
        cw, ch, cx, cy = max(c, key=lambda k: (c[k], k[0] * k[1]))
        # Mod 2 (einzige echte Encoder-Anforderung)
        cw = (cw // 2) * 2
        ch = (ch // 2) * 2
        cx = (cx // 2) * 2
        cy = (cy // 2) * 2
        if cw <= 0 or ch <= 0:
            return None
        if cw < w * 0.5 or ch < h * 0.5:
            return None
        if (w - cw) < 4 and (h - ch) < 4:
            return None
        if cx + cw > w or cy + ch > h:
            return None
        crop = f"crop={cw}:{ch}:{cx}:{cy}"
        mode_note = "Mehrpunkt" if mode == "multi" else "Einzelpunkt"
        worker._logger.info(
            f"Auto-Crop: {crop} ({mode_note}, Quelle: {w}x{h}, beschnitten: {w-cw}×{h-ch}px)"
        )
        return crop

    # ------------------------------------------------------------------
    def detect_imax_auto(
        self,
        path: str,
        duration_s: float,
        source_w: int = 0,
        source_h: int = 0,
        interval_s: int = 90,
        probe_duration_s: int = 3,
        min_variance_percent: int = 15,
        min_hits: int = 2,
    ) -> bool:
        """Analysiert die aktive Bildfläche im Film auf wechselndes Format."""
        worker = self.worker
        interval_s = _sanitize_imax_interval(interval_s)
        probe_duration_s = max(1, min(30, _safe_int(probe_duration_s, 3)))
        min_variance_percent = max(1, min(100, _safe_int(min_variance_percent, 15)))
        min_hits = max(2, min(50, _safe_int(min_hits, 2)))
        offsets = _imax_probe_offsets(duration_s, interval_s)
        if not offsets:
            return False

        ratios = []
        for offset in offsets:
            try:
                cmd = [
                    worker.tools.ffmpeg, "-hide_banner", "-ss", str(offset), "-i", path,
                    "-t", str(probe_duration_s), "-vf", "cropdetect=limit=0.08:round=2:reset=1",
                    "-an", "-sn", "-f", "null", "-",
                ]
                r = subprocess.run(
                    cmd, capture_output=True, text=True, encoding="utf-8",
                    errors="replace", **_no_window_kwargs(),
                    timeout=max(20, probe_duration_s + 20),
                )
                raw = (r.stderr or "") + (r.stdout or "")
                crop = _best_crop_from_output(raw, source_w=source_w, source_h=source_h)
                if not crop:
                    continue
                cw, ch, _cx, _cy = crop
                if cw <= 0 or ch <= 0:
                    continue
                if source_w and source_h and (cw < source_w * 0.5 or ch < source_h * 0.5):
                    continue
                ratios.append(round(cw / ch, 3))
            except Exception as e:
                worker.log(
                    f"⚠️ IMAX-Auto-Probe bei Offset {offset}s fehlgeschlagen: {e}",
                    "warn",
                )
                worker.log(traceback.format_exc(), "error")
                continue
        if len(ratios) < min_hits:
            return False
        r_min, r_max = min(ratios), max(ratios)
        variance = (r_max - r_min) / r_min if r_min > 0 else 0
        detected = variance > (min_variance_percent / 100.0)
        if detected:
            worker.log(
                f"🎬 IMAX-Auto: wechselndes aktives AR {r_min:.2f}-{r_max:.2f} "
                f"bei {len(ratios)} Prüfpunkten alle {interval_s}s "
                f"(Schwelle {min_variance_percent}%) → IMAX aktiviert",
                "info",
            )
        return detected
