"""Owned packet timing and PGS extraction evidence for bitmap OCR."""

import json
import math
import tempfile
from pathlib import Path
from ..core.bitmap_subtitle_ocr import BitmapSubtitlePacket, normalize_packets
from ..core.pgs_display_set import parse_pgs_sup_file
from ..subtitle.matroska_tracks import resolve_subtitle_track_id


class BitmapSubtitlePacketProbe:
    def __init__(self, *, tools, run, log, available):
        self.tools, self.run, self.log, self.available = tools, run, log, available

    def probe_packets_ffprobe(
        self, path: str, stream_index: int, ffprobe: str
    ) -> list[BitmapSubtitlePacket]:
        cmd = [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            str(int(stream_index)),
            "-show_packets",
            "-show_entries",
            "packet=pts_time,duration_time",
            "-of",
            "json",
            str(path),
        ]
        result = self.run(cmd, allow_error=True, timeout=180)
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

    def probe_pgs_display_sets(
        self, path: str, stream_index: int, ffprobe: str, *, extract_sup
    ) -> list[BitmapSubtitlePacket]:
        if Path(path).suffix.casefold() != ".mkv":
            return []
        with tempfile.TemporaryDirectory(prefix="dragon_pgs_timing_") as tmp:
            sup_path = Path(tmp) / "timing.sup"
            extraction = extract_sup(path, stream_index, sup_path, ffprobe)
            if not extraction:
                return []
            try:
                parsed = parse_pgs_sup_file(sup_path)
            except (OSError, ValueError, TypeError) as exc:
                self.log(f"PGS-Display-Set-Parser fehlgeschlagen: {exc}", "warn")
                return []

        stats = parsed.stats
        if parsed.warnings:
            # Keep logs useful on corrupt streams without flooding one line per
            # recovery point. The complete counts still make damage visible.
            self.log(
                f"PGS-Parser: {len(parsed.warnings)} Strukturwarnung(en), "
                f"{stats.malformed_segments} fehlerhafte Segmente, {stats.resync_count} Resync(s).",
                "warn",
            )
        self.log(
            f"PGS-Parser ({extraction}): {stats.display_sets} Display Sets, "
            f"{stats.visible_events} sichtbar, {stats.clear_events} Clear, "
            f"{len(parsed.cues)} OCR-Cues.",
            "info",
        )
        return normalize_packets(
            BitmapSubtitlePacket(cue.start_s, cue.end_s) for cue in parsed.cues
        )

    def extract_pgs_sup(
        self, path: str, stream_index: int, target: Path, ffprobe: str, *, resolve_track
    ) -> str | None:
        """Extract one PGS track for timing analysis.

        MKVToolNix is preferred because it copies the Matroska subtitle track
        without passing packets through FFmpeg's SUP muxer. FFmpeg remains a
        compatibility fallback when MKVToolNix is unavailable or identification
        fails.
        """
        mkvmerge = str(getattr(self.tools, "mkvmerge", "") or "").strip()
        mkvextract = str(getattr(self.tools, "mkvextract", "") or "").strip()
        if (
            mkvmerge
            and mkvextract
            and self.available(mkvmerge)
            and self.available(mkvextract)
        ):
            track_id = resolve_track(path, stream_index, ffprobe, mkvmerge)
            if track_id is not None:
                try:
                    result = self.run(
                        [mkvextract, "tracks", str(path), f"{track_id}:{target}"],
                        allow_error=True,
                        timeout=300,
                    )
                except RuntimeError as exc:
                    self.log(
                        f"PGS-Timing: mkvextract fehlgeschlagen, FFmpeg-Fallback folgt: {exc}",
                        "warn",
                    )
                    result = None
                if (
                    result is not None
                    and result.returncode == 0
                    and self.valid_sup(target)
                ):
                    return "MKVToolNix"
                try:
                    target.unlink(missing_ok=True)
                except OSError:
                    pass

        ffmpeg = str(getattr(self.tools, "ffmpeg", "") or "ffmpeg")
        try:
            result = self.run(
                [
                    ffmpeg,
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-fflags",
                    "+discardcorrupt",
                    "-err_detect",
                    "ignore_err",
                    "-i",
                    str(path),
                    "-map",
                    f"0:{int(stream_index)}",
                    "-c:s",
                    "copy",
                    "-f",
                    "sup",
                    str(target),
                ],
                allow_error=True,
                timeout=300,
            )
        except RuntimeError as exc:
            self.log(f"PGS-Timing: FFmpeg-SUP-Extraktion fehlgeschlagen: {exc}", "warn")
            return None
        if self.valid_sup(target):
            # A non-zero FFmpeg return code may occur after useful packets were
            # already written. The native parser can decide whether the partial
            # SUP still contains usable display sets.
            return "FFmpeg" if result.returncode == 0 else "FFmpeg-partiell"
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        return None

    def mkv_track_id_for_stream(
        self, path: str, stream_index: int, ffprobe: str, mkvmerge: str
    ) -> int | None:
        try:
            probe = self.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-select_streams",
                    "s",
                    "-show_entries",
                    "stream=index",
                    "-of",
                    "json",
                    str(path),
                ],
                allow_error=True,
                timeout=60,
            )
        except RuntimeError:
            return None
        if probe.returncode != 0:
            return None
        try:
            identify = self.run(
                [mkvmerge, "-J", str(path)], allow_error=True, timeout=60
            )
        except RuntimeError:
            return None
        if identify.returncode != 0:
            return None
        try:
            return resolve_subtitle_track_id(
                probe.stdout, identify.stdout, stream_index
            )
        except (IndexError, ValueError, TypeError, KeyError):
            return None

    @staticmethod
    def valid_sup(path: Path) -> bool:
        try:
            if not path.is_file() or path.stat().st_size < 13:
                return False
            with path.open("rb") as handle:
                return handle.read(2) == b"PG"
        except OSError:
            return False
