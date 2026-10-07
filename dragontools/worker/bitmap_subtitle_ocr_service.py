# -*- coding: utf-8 -*-
"""Assistive PGS/VobSub -> SRT OCR pipeline used by Patch J."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Callable

from ..core.bitmap_subtitle_ocr import (
    BitmapOcrCue,
    BitmapOcrDraft,
    BitmapSubtitlePacket,
    normalize_packets,
    parse_tesseract_tsv,
    serialize_srt,
    merge_adjacent_duplicate_cues,
    write_pending_draft,
    source_signature,
)
from ..core.media_library_fix_queue import MediaLibraryFixIssue
from ..core.pgs_display_set import parse_pgs_sup_file
from ..core.process_runner import tool_available
from .tool_runner import run_tool
from .log_dispatch import dispatch_log
from .bitmap_subtitle_packet_probe import BitmapSubtitlePacketProbe
from ..subtitle.output_safety import stopped
from ..core.settings_media_library import (
    DEFAULT_MEDIA_LIBRARY_OCR_LANGUAGES,
    DEFAULT_MEDIA_LIBRARY_OCR_MIN_CONFIDENCE,
    SET_KEY_MEDIA_LIBRARY_OCR_LANGUAGES,
    SET_KEY_MEDIA_LIBRARY_OCR_MIN_CONFIDENCE,
)


LogFn = Callable[[str, str], None] | None


def _write_srt_exclusive(target: Path, content: str) -> Path:
    """Write *content* without ever replacing a pre-existing sidecar.

    The final path is reserved with ``open("x")``.  If writing fails, only
    the inode created by this call is removed; a racing/existing user file is
    never unlinked.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    identity: tuple[int, int] | None = None
    try:
        with target.open("x", encoding="utf-8", newline="\n") as handle:
            stat = os.fstat(handle.fileno())
            identity = (stat.st_dev, stat.st_ino)
            handle.write(content)
    except Exception:
        if identity is not None:
            try:
                current = target.lstat()
                if (current.st_dev, current.st_ino) == identity:
                    target.unlink()
            except OSError:
                pass
        raise
    try:
        if not target.is_file() or target.stat().st_size <= 0:
            raise RuntimeError("PGS→SRT hat keine gültige SRT-Datei erzeugt.")
    except Exception:
        if identity is not None:
            try:
                current = target.lstat()
                if (current.st_dev, current.st_ino) == identity:
                    target.unlink()
            except OSError:
                pass
        raise
    return target


def run_analysis_tool(cmd, *, allow_error=True, timeout=None, worker=None, log=None):
    return run_tool(cmd, label="Bitmap-Untertitel OCR", timeout_s=timeout,
                    worker=worker, log=log)


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

    def _run_analysis(self, cmd, *, allow_error=True, timeout=None):
        if self._abort_requested():
            raise RuntimeError("OCR wurde abgebrochen.")
        result = run_analysis_tool(cmd, allow_error=allow_error, timeout=timeout,
                                   worker=self.worker, log=self.log)
        if stopped(result, self.worker):
            raise RuntimeError("OCR wurde abgebrochen oder hat das Zeitlimit überschritten.")
        return result

    def _packet_probe(self):
        return BitmapSubtitlePacketProbe(tools=self.tools, run=self._run_analysis,
                                         log=self._log, available=tool_available)

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

        packets = self._probe_packets(issue.path, issue.stream_index, ffprobe, issue.codec)
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
            expected_source_signature=getattr(issue, "source_signature", None),
        )

    def create_srt(self, issue: MediaLibraryFixIssue, target_path: str | Path) -> Path:
        """Create a final SRT for an encode job.

        Unlike the Media-Library review workflow this method is explicitly
        best-effort at the caller boundary. It never modifies/removes the
        bitmap source stream; callers decide how OCR failures are logged.
        """
        if issue.stream_index is None or not issue.stream_ordinal:
            raise RuntimeError("Bilduntertitel besitzt keinen eindeutigen Streamindex.")
        ffmpeg = str(getattr(self.tools, "ffmpeg", "") or "ffmpeg")
        ffprobe = str(getattr(self.tools, "ffprobe", "") or "ffprobe")
        tesseract = str(getattr(self.tools, "tesseract", "") or "tesseract")
        for label, tool in (("FFmpeg", ffmpeg), ("FFprobe", ffprobe), ("Tesseract", tesseract)):
            if not tool_available(tool):
                raise RuntimeError(f"{label} wurde für Bitmap-OCR nicht gefunden.")

        packets = self._probe_packets(issue.path, issue.stream_index, ffprobe, issue.codec)
        if not packets:
            raise RuntimeError("FFprobe hat keine lesbaren PGS/SUP-Untertitelpakete gefunden.")
        self._validate_tesseract_languages(tesseract)
        cues: list[BitmapOcrCue] = []
        total = len(packets)
        with tempfile.TemporaryDirectory(prefix="dragon_encode_ocr_") as tmp:
            tmp_dir = Path(tmp)
            for number, packet in enumerate(packets, start=1):
                if self._abort_requested():
                    raise RuntimeError("OCR wurde abgebrochen.")
                image = tmp_dir / f"cue_{number:06d}.png"
                if not self._render_subtitle_image(issue, packet, image, ffmpeg):
                    self._log(f"PGS→SRT Cue {number}/{total}: PGS-Bild konnte nicht gelesen/gerendert werden.", "warn")
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
        if self._abort_requested():
            raise RuntimeError("OCR wurde abgebrochen.")
        signature = getattr(issue, "source_signature", None)
        if signature and tuple(signature) != source_signature(issue.path):
            raise ValueError("OCR-Quelldatei wurde während der Verarbeitung verändert.")
        normalized = merge_adjacent_duplicate_cues(cues)
        if not normalized:
            raise RuntimeError("PGS→SRT hat keinen verwertbaren OCR-Text erzeugt.")
        target = Path(target_path)
        try:
            return _write_srt_exclusive(target, serialize_srt(normalized))
        except FileExistsError as exc:
            raise FileExistsError(f"SRT-Zieldatei existiert bereits: {target.name}") from exc

    def _probe_packets(
        self, path: str, stream_index: int, ffprobe: str, codec: str = ""
    ) -> list[BitmapSubtitlePacket]:
        """Return bitmap subtitle visibility intervals.

        PGS uses the native SUP display-set parser first. FFprobe remains the
        fallback for damaged/unextractable PGS and the primary path for VobSub.
        """
        if self._abort_requested():
            raise RuntimeError("OCR wurde abgebrochen.")
        normalized_codec = str(codec or "").strip().casefold()
        if normalized_codec in {"hdmv_pgs_subtitle", "pgs"}:
            display_set_packets = self._probe_pgs_display_sets(path, stream_index, ffprobe)
            if display_set_packets:
                return display_set_packets
            self._log(
                "PGS-Display-Set-Parser lieferte keine Cues; FFprobe-Timing wird als Fallback verwendet.",
                "warn",
            )
        return self._probe_packets_ffprobe(path, stream_index, ffprobe)

    def _probe_packets_ffprobe(self, path, stream_index, ffprobe):
        return self._packet_probe().probe_packets_ffprobe(path, stream_index, ffprobe)

    def _probe_pgs_display_sets(self, path, stream_index, ffprobe):
        return self._packet_probe().probe_pgs_display_sets(path, stream_index, ffprobe,
            extract_sup=self._extract_pgs_sup)

    def _extract_pgs_sup(self, path, stream_index, target, ffprobe):
        return self._packet_probe().extract_pgs_sup(path, stream_index, target, ffprobe,
            resolve_track=self._mkv_track_id_for_stream)

    def _mkv_track_id_for_stream(self, path, stream_index, ffprobe, mkvmerge):
        return self._packet_probe().mkv_track_id_for_stream(path, stream_index, ffprobe, mkvmerge)

    @staticmethod
    def _valid_sup(path):
        return BitmapSubtitlePacketProbe.valid_sup(path)

    def _render_subtitle_image(
        self,
        issue: MediaLibraryFixIssue,
        packet: BitmapSubtitlePacket,
        target: Path,
        ffmpeg: str,
    ) -> bool:
        subtitle_ordinal = max(0, int(issue.stream_ordinal or 1) - 1)

        # Do not open the demuxer directly at the cue midpoint. PGS display
        # sets can depend on composition/palette/object segments immediately
        # before the visible image. A hard seek into that sequence is a common
        # cause of "Not enough data" / empty-overlay failures. Read a short
        # preroll first, then seek locally to a point just after cue start.
        cue_duration = max(0.10, packet.end_s - packet.start_s)
        sample_time = packet.start_s + min(0.12, cue_duration * 0.20)
        preroll_s = min(3.0, sample_time)
        input_seek = max(0.0, sample_time - preroll_s)
        local_seek = max(0.0, sample_time - input_seek)

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
            "-fflags", "+discardcorrupt", "-err_detect", "ignore_err",
            "-ss", f"{input_seek:.3f}",
            "-i", str(issue.path),
            "-ss", f"{local_seek:.3f}",
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-frames:v", "1",
            str(target),
        ]
        result = self._run_analysis(cmd, allow_error=True, timeout=90)
        if result.returncode == 0 and self._valid_image(target):
            return True

        # Conservative fallback for FFmpeg builds where blend/bitmap subtitle
        # synchronization behaves differently.  It keeps the video background,
        # which may reduce confidence but still produces a reviewable draft.
        fallback = [
            ffmpeg,
            "-y", "-hide_banner", "-loglevel", "error",
            "-fflags", "+discardcorrupt", "-err_detect", "ignore_err",
            "-ss", f"{input_seek:.3f}",
            "-i", str(issue.path),
            "-ss", f"{local_seek:.3f}",
            "-filter_complex", f"[0:v:0][0:s:{subtitle_ordinal}]overlay[out]",
            "-map", "[out]",
            "-frames:v", "1",
            str(target),
        ]
        result = self._run_analysis(fallback, allow_error=True, timeout=90)
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
        result = self._run_analysis(cmd, allow_error=True, timeout=60)
        if result.returncode != 0:
            return "", 0.0
        return parse_tesseract_tsv(result.stdout or "")

    def _validate_tesseract_languages(self, tesseract: str) -> None:
        requested = {item.strip() for item in self.languages.split("+") if item.strip()}
        if not requested:
            raise RuntimeError("Keine Tesseract-OCR-Sprache konfiguriert.")
        result = self._run_analysis([tesseract, "--list-langs"], allow_error=True, timeout=30)
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
        if self.worker is None:
            return False
        state = getattr(self.worker, "_control_state", None)
        requested = bool(getattr(state, "abort_requested", False)) if state is not None else bool(getattr(self.worker, "abort_requested", False))
        abort_type = getattr(state, "abort_type", None) if state is not None else getattr(self.worker, "abort_type", None)
        return bool(requested and abort_type == "sofort")

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
        dispatch_log(self.log, message, level)


__all__ = ["BitmapSubtitleOcrService"]
