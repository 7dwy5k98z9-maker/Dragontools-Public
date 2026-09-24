# -*- coding: utf-8 -*-
"""Assistive PGS/VobSub -> SRT OCR pipeline used by Patch J."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
from typing import Callable

from ..core.bitmap_subtitle_ocr import (
    BitmapOcrCue,
    BitmapOcrDraft,
    BitmapSubtitlePacket,
    normalize_packets,
    parse_tesseract_tsv,
    write_pending_draft,
)
from ..core.media_library_fix_queue import MediaLibraryFixIssue
from ..core.process_runner import run_analysis_tool, tool_available
from ..core.settings_media_library import (
    DEFAULT_MEDIA_LIBRARY_OCR_LANGUAGES,
    DEFAULT_MEDIA_LIBRARY_OCR_MIN_CONFIDENCE,
    SET_KEY_MEDIA_LIBRARY_OCR_LANGUAGES,
    SET_KEY_MEDIA_LIBRARY_OCR_MIN_CONFIDENCE,
)


LogFn = Callable[[str, str], None] | None


class BitmapSubtitleOcrService:
    def __init__(self, *, settings, tools, log: LogFn = None, worker=None) -> None:
        self.settings = settings
        self.tools = tools
        self.log = log
        self.worker = worker
        self.min_confidence = self._setting_int(
            SET_KEY_MEDIA_LIBRARY_OCR_MIN_CONFIDENCE,
            DEFAULT_MEDIA_LIBRARY_OCR_MIN_CONFIDENCE,
            minimum=30,
            maximum=99,
        ) / 100.0
        self.languages = self._setting_str(
            SET_KEY_MEDIA_LIBRARY_OCR_LANGUAGES,
            DEFAULT_MEDIA_LIBRARY_OCR_LANGUAGES,
        )

    def create_draft(self, issue: MediaLibraryFixIssue) -> BitmapOcrDraft:
        if Path(issue.path).suffix.casefold() != ".mkv":
            raise RuntimeError("Bitmap-OCR ist in Patch J nur für MKV-Quellen aktiviert.")
        if issue.stream_index is None or not issue.stream_ordinal:
            raise RuntimeError("Bilduntertitel besitzt keinen eindeutigen Streamindex.")
        ffmpeg = str(getattr(self.tools, "ffmpeg", "") or "ffmpeg")
        ffprobe = str(getattr(self.tools, "ffprobe", "") or "ffprobe")
        tesseract = str(getattr(self.tools, "tesseract", "") or "tesseract")
        for label, tool in (("FFmpeg", ffmpeg), ("FFprobe", ffprobe), ("Tesseract", tesseract)):
            if not tool_available(tool):
                raise RuntimeError(f"{label} wurde für Bitmap-OCR nicht gefunden.")

        packets = self._probe_packets(issue.path, issue.stream_index, ffprobe)
        if not packets:
            raise RuntimeError("FFprobe hat keine Bilduntertitel-Pakete gefunden.")
        self._validate_tesseract_languages(tesseract)
        cues: list[BitmapOcrCue] = []
        total = len(packets)
        with tempfile.TemporaryDirectory(prefix="dragon_ocr_") as tmp:
            tmp_dir = Path(tmp)
            for number, packet in enumerate(packets, start=1):
                if self._abort_requested():
                    raise RuntimeError("OCR wurde abgebrochen.")
                image = tmp_dir / f"cue_{number:06d}.png"
                if not self._render_subtitle_image(issue, packet, image, ffmpeg):
                    self._log(f"OCR Cue {number}/{total}: Bild konnte nicht gerendert werden.", "warn")
                    continue
                text, confidence = self._ocr_image(image, tesseract)
                if not text.strip():
                    continue
                cues.append(BitmapOcrCue(
                    index=len(cues) + 1,
                    start_s=packet.start_s,
                    end_s=packet.end_s,
                    text=text,
                    confidence=confidence,
                    uncertain=confidence < self.min_confidence,
                ))
                if number == 1 or number % 25 == 0 or number == total:
                    self._log(
                        f"Bitmap-OCR {number}/{total}: {len(cues)} Text-Cues erkannt.",
                        "info",
                    )
        if self._abort_requested():
            raise RuntimeError("OCR wurde abgebrochen.")
        return write_pending_draft(
            media_path=issue.path,
            stream_ordinal=int(issue.stream_ordinal),
            stream_index=issue.stream_index,
            codec=issue.codec,
            source_language=issue.language,
            forced=issue.forced,
            cues=cues,
            min_confidence=self.min_confidence,
        )

    def _probe_packets(self, path: str, stream_index: int, ffprobe: str) -> list[BitmapSubtitlePacket]:
        cmd = [
            ffprobe,
            "-v", "error",
            "-select_streams", str(int(stream_index)),
            "-show_packets",
            "-show_entries", "packet=pts_time,duration_time",
            "-of", "json",
            str(path),
        ]
        result = run_analysis_tool(cmd, allow_error=True, timeout=180)
        if result.returncode != 0:
            return []
        try:
            data = json.loads(result.stdout or "{}")
        except json.JSONDecodeError:
            return []
        raw: list[tuple[float, float | None]] = []
        for item in data.get("packets") or []:
            try:
                start = float(item.get("pts_time"))
            except (TypeError, ValueError):
                continue
            try:
                duration = float(item.get("duration_time"))
            except (TypeError, ValueError):
                duration = None
            raw.append((start, duration if duration and duration > 0 else None))
        raw.sort(key=lambda item: item[0])
        packets: list[BitmapSubtitlePacket] = []
        for index, (start, duration) in enumerate(raw):
            next_start = raw[index + 1][0] if index + 1 < len(raw) else None
            if duration is not None:
                end = start + min(duration, 30.0)
            elif next_start is not None and next_start > start:
                end = min(next_start, start + 8.0)
            else:
                end = start + 4.0
            packets.append(BitmapSubtitlePacket(start, max(start + 0.10, end)))
        return normalize_packets(packets)

    def _render_subtitle_image(
        self,
        issue: MediaLibraryFixIssue,
        packet: BitmapSubtitlePacket,
        target: Path,
        ffmpeg: str,
    ) -> bool:
        subtitle_ordinal = max(0, int(issue.stream_ordinal or 1) - 1)
        midpoint = packet.midpoint_s
        # Difference against the same clean video frame isolates the bitmap
        # subtitle far better than OCR on the normal picture background.
        filter_complex = (
            f"[0:v:0]split=2[base][overlaybase];"
            f"[overlaybase][0:s:{subtitle_ordinal}]overlay[subbed];"
            f"[subbed][base]blend=all_mode=difference,format=gray,negate[out]"
        )
        cmd = [
            ffmpeg,
            "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{midpoint:.3f}",
            "-i", str(issue.path),
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-frames:v", "1",
            str(target),
        ]
        result = run_analysis_tool(cmd, allow_error=True, timeout=90)
        if result.returncode == 0 and self._valid_image(target):
            return True

        # Conservative fallback for FFmpeg builds where blend/bitmap subtitle
        # synchronization behaves differently.  It keeps the video background,
        # which may reduce confidence but still produces a reviewable draft.
        fallback = [
            ffmpeg,
            "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{midpoint:.3f}",
            "-i", str(issue.path),
            "-filter_complex", f"[0:v:0][0:s:{subtitle_ordinal}]overlay[out]",
            "-map", "[out]",
            "-frames:v", "1",
            str(target),
        ]
        result = run_analysis_tool(fallback, allow_error=True, timeout=90)
        return result.returncode == 0 and self._valid_image(target)

    def _ocr_image(self, image: Path, tesseract: str) -> tuple[str, float]:
        cmd = [
            tesseract,
            str(image),
            "stdout",
            "-l", self.languages,
            "--psm", "11",
            "tsv",
        ]
        result = run_analysis_tool(cmd, allow_error=True, timeout=60)
        if result.returncode != 0:
            return "", 0.0
        return parse_tesseract_tsv(result.stdout or "")

    def _validate_tesseract_languages(self, tesseract: str) -> None:
        requested = {item.strip() for item in self.languages.split("+") if item.strip()}
        if not requested:
            raise RuntimeError("Keine Tesseract-OCR-Sprache konfiguriert.")
        result = run_analysis_tool([tesseract, "--list-langs"], allow_error=True, timeout=30)
        if result.returncode != 0:
            return
        installed = {
            line.strip() for line in (result.stdout or "").splitlines()
            if line.strip() and not line.lower().startswith("list of available")
        }
        missing = sorted(requested - installed)
        if missing:
            raise RuntimeError(
                "Tesseract-Sprachdaten fehlen: " + ", ".join(missing)
                + ". Installiert: " + (", ".join(sorted(installed)) or "keine erkannt")
            )

    @staticmethod
    def _valid_image(path: Path) -> bool:
        try:
            return path.is_file() and path.stat().st_size > 100
        except OSError:
            return False

    def _abort_requested(self) -> bool:
        return bool(self.worker is not None and getattr(self.worker, "abort_requested", False))

    def _setting_int(self, key: str, default: int, *, minimum: int, maximum: int) -> int:
        try:
            value = int(self.settings.value(key, default, type=int))
        except (AttributeError, TypeError, ValueError):
            value = int(default)
        return max(minimum, min(maximum, value))

    def _setting_str(self, key: str, default: str) -> str:
        try:
            value = str(self.settings.value(key, default, type=str) or default).strip()
        except (AttributeError, TypeError):
            value = default
        return value or default

    def _log(self, message: str, level: str = "info") -> None:
        if callable(self.log):
            self.log(message, level)


__all__ = ["BitmapSubtitleOcrService"]
