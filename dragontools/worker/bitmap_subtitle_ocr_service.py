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
    serialize_srt,
    merge_adjacent_duplicate_cues,
    write_pending_draft,
)
from ..core.media_library_fix_queue import MediaLibraryFixIssue
from ..core.pgs_display_set import parse_pgs_sup_file
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
        normalized = merge_adjacent_duplicate_cues(cues)
        if not normalized:
            raise RuntimeError("PGS→SRT hat keinen verwertbaren OCR-Text erzeugt.")
        target = Path(target_path)
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"SRT-Zieldatei existiert bereits: {target.name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(serialize_srt(normalized), encoding="utf-8", newline="\n")
        if not target.is_file() or target.stat().st_size <= 0:
            raise RuntimeError("PGS→SRT hat keine gültige SRT-Datei erzeugt.")
        return target

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

    def _probe_packets_ffprobe(
        self, path: str, stream_index: int, ffprobe: str
    ) -> list[BitmapSubtitlePacket]:
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

    def _probe_pgs_display_sets(
        self, path: str, stream_index: int, ffprobe: str
    ) -> list[BitmapSubtitlePacket]:
        if Path(path).suffix.casefold() != ".mkv":
            return []
        with tempfile.TemporaryDirectory(prefix="dragon_pgs_timing_") as tmp:
            sup_path = Path(tmp) / "timing.sup"
            extraction = self._extract_pgs_sup(path, stream_index, sup_path, ffprobe)
            if not extraction:
                return []
            try:
                parsed = parse_pgs_sup_file(sup_path)
            except (OSError, ValueError, TypeError) as exc:
                self._log(f"PGS-Display-Set-Parser fehlgeschlagen: {exc}", "warn")
                return []

        stats = parsed.stats
        if parsed.warnings:
            # Keep logs useful on corrupt streams without flooding one line per
            # recovery point. The complete counts still make damage visible.
            self._log(
                f"PGS-Parser: {len(parsed.warnings)} Strukturwarnung(en), "
                f"{stats.malformed_segments} fehlerhafte Segmente, {stats.resync_count} Resync(s).",
                "warn",
            )
        self._log(
            f"PGS-Parser ({extraction}): {stats.display_sets} Display Sets, "
            f"{stats.visible_events} sichtbar, {stats.clear_events} Clear, "
            f"{len(parsed.cues)} OCR-Cues.",
            "info",
        )
        return normalize_packets(
            BitmapSubtitlePacket(cue.start_s, cue.end_s) for cue in parsed.cues
        )

    def _extract_pgs_sup(
        self, path: str, stream_index: int, target: Path, ffprobe: str
    ) -> str | None:
        """Extract one PGS track for timing analysis.

        MKVToolNix is preferred because it copies the Matroska subtitle track
        without passing packets through FFmpeg's SUP muxer. FFmpeg remains a
        compatibility fallback when MKVToolNix is unavailable or identification
        fails.
        """
        mkvmerge = str(getattr(self.tools, "mkvmerge", "") or "").strip()
        mkvextract = str(getattr(self.tools, "mkvextract", "") or "").strip()
        if (mkvmerge and mkvextract and tool_available(mkvmerge) and tool_available(mkvextract)):
            track_id = self._mkv_track_id_for_stream(path, stream_index, ffprobe, mkvmerge)
            if track_id is not None:
                try:
                    result = run_analysis_tool(
                        [mkvextract, "tracks", str(path), f"{track_id}:{target}"],
                        allow_error=True,
                        timeout=300,
                    )
                except RuntimeError as exc:
                    self._log(f"PGS-Timing: mkvextract fehlgeschlagen, FFmpeg-Fallback folgt: {exc}", "warn")
                    result = None
                if result is not None and result.returncode == 0 and self._valid_sup(target):
                    return "MKVToolNix"
                try:
                    target.unlink(missing_ok=True)
                except OSError:
                    pass

        ffmpeg = str(getattr(self.tools, "ffmpeg", "") or "ffmpeg")
        try:
            result = run_analysis_tool(
                [
                    ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                    "-fflags", "+discardcorrupt", "-err_detect", "ignore_err",
                    "-i", str(path), "-map", f"0:{int(stream_index)}",
                    "-c:s", "copy", "-f", "sup", str(target),
                ],
                allow_error=True,
                timeout=300,
            )
        except RuntimeError as exc:
            self._log(f"PGS-Timing: FFmpeg-SUP-Extraktion fehlgeschlagen: {exc}", "warn")
            return None
        if self._valid_sup(target):
            # A non-zero FFmpeg return code may occur after useful packets were
            # already written. The native parser can decide whether the partial
            # SUP still contains usable display sets.
            return "FFmpeg" if result.returncode == 0 else "FFmpeg-partiell"
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        return None

    def _mkv_track_id_for_stream(
        self, path: str, stream_index: int, ffprobe: str, mkvmerge: str
    ) -> int | None:
        try:
            probe = run_analysis_tool(
                [
                    ffprobe, "-v", "error", "-select_streams", "s",
                    "-show_entries", "stream=index", "-of", "json", str(path),
                ],
                allow_error=True,
                timeout=60,
            )
        except RuntimeError:
            return None
        if probe.returncode != 0:
            return None
        try:
            stream_rows = json.loads(probe.stdout or "{}").get("streams") or []
            subtitle_indices = [int(row["index"]) for row in stream_rows if "index" in row]
            subtitle_ordinal = subtitle_indices.index(int(stream_index))
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None

        try:
            identify = run_analysis_tool(
                [mkvmerge, "-J", str(path)], allow_error=True, timeout=60
            )
        except RuntimeError:
            return None
        if identify.returncode != 0:
            return None
        try:
            tracks = json.loads(identify.stdout or "{}").get("tracks") or []
            subtitle_tracks = [
                row for row in tracks
                if str(row.get("type") or "").casefold() == "subtitles"
            ]
            return int(subtitle_tracks[subtitle_ordinal]["id"])
        except (IndexError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None

    @staticmethod
    def _valid_sup(path: Path) -> bool:
        try:
            if not path.is_file() or path.stat().st_size < 13:
                return False
            with path.open("rb") as handle:
                return handle.read(2) == b"PG"
        except OSError:
            return False

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
        result = run_analysis_tool(cmd, allow_error=True, timeout=90)
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
