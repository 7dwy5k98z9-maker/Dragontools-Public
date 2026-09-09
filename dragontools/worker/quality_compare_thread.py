# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import subprocess
import threading
import traceback
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from ..core.media_analyzer import analyze_media
from ..core.paths import get_tool_paths
from ..core.quality_tester import (
    QualityComparisonResult,
    QualityComparisonSummary,
    QualityFileInfo,
    automatic_quality_segments,
    comparison_duration_limit,
    comparison_segment_starts,
    parse_quality_segments,
    quality_comparison_assessment,
)
from ..core.timeout_settings import get_timeout
from .process_control import terminate_process_tree
from .tool_runner import run_tool


class QualityCompareThread(QThread):
    """Vergleicht zwei bereits vorhandene Videodateien segmentweise.

    Datei A ist bewusst die Referenz. Datei B wird relativ zu A mit SSIM/VMAF
    bewertet. Ohne echte Referenzquelle ist daraus kein absoluter Qualitätsgewinner
    ableitbar; die Auswertung beschreibt daher Ähnlichkeit plus Größenunterschied.
    """

    log_line = pyqtSignal(str)
    progress = pyqtSignal(int)
    result_ready = pyqtSignal(object)
    summary_ready = pyqtSignal(object)
    finished = pyqtSignal()

    def __init__(
        self,
        file_a: str,
        file_b: str,
        *,
        sample_count: int = 3,
        sample_duration_s: int = 20,
        manual_ranges: str = "",
        offset_b_s: float = 0.0,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.file_a = str(Path(file_a).resolve())
        self.file_b = str(Path(file_b).resolve())
        self.sample_count = max(1, min(20, int(sample_count or 3)))
        self.sample_duration_s = max(1, int(sample_duration_s or 20))
        self.manual_ranges = str(manual_ranges or "")
        self.offset_b_s = float(offset_b_s or 0.0)
        self.tools = get_tool_paths()
        self.current_process: subprocess.Popen | None = None
        self._process_lock = threading.Lock()
        self._abort = False
        self.abort_requested = False
        self.abort_type: str | None = None

    def cancel(self) -> None:
        self._abort = True
        self.abort_requested = True
        self.abort_type = "sofort"
        terminate_process_tree(
            self,
            self._process_lock,
            log=lambda message, _level="warn": self.log_line.emit(message),
            attr_name="current_process",
            label="Qualitätsvergleich-Prozess",
        )

    def run(self) -> None:
        try:
            self._run()
        except Exception:
            self.log_line.emit("❌ Unbehandelte Ausnahme im Dateivergleich:")
            self.log_line.emit(traceback.format_exc())
        finally:
            with self._process_lock:
                self.current_process = None
            self.finished.emit()

    def _run(self) -> None:
        if self.file_a == self.file_b:
            self.log_line.emit("⚠️ Datei A und Datei B sind identisch.")
            return
        if not Path(self.file_a).is_file() or not Path(self.file_b).is_file():
            self.log_line.emit("❌ Eine der beiden Vergleichsdateien existiert nicht.")
            return

        self.log_line.emit(f"▶ Referenz A: {Path(self.file_a).name}")
        self.log_line.emit(f"▶ Kandidat B: {Path(self.file_b).name}")
        if abs(self.offset_b_s) > 0.0005:
            self.log_line.emit(f"ℹ️  Zeitversatz B: {self.offset_b_s:+.3f}s")

        media_a = analyze_media(self.file_a, self.tools)
        media_b = analyze_media(self.file_b, self.tools)
        info_a = self._file_info(media_a, self.file_a)
        info_b = self._file_info(media_b, self.file_b)

        if info_a.duration_s <= 0 or info_b.duration_s <= 0:
            self.log_line.emit("❌ Laufzeit konnte für mindestens eine Datei nicht bestimmt werden.")
            return

        duration_delta = abs(info_a.duration_s - info_b.duration_s)
        if duration_delta > max(1.0, min(info_a.duration_s, info_b.duration_s) * 0.005):
            self.log_line.emit(
                f"⚠️ Laufzeiten unterscheiden sich um {duration_delta:.3f}s. "
                "Bei abweichendem Schnitt oder Intro sind SSIM/VMAF ohne passenden Offset nicht aussagekräftig."
            )

        if (info_a.width, info_a.height) != (info_b.width, info_b.height):
            self.log_line.emit(
                f"ℹ️  Unterschiedliche Auflösung: A {info_a.width}×{info_a.height}, "
                f"B {info_b.width}×{info_b.height}. Für die Metrik wird A auf B-Auflösung skaliert."
            )
            if info_a.width > 0 and info_a.height > 0 and info_b.width > 0 and info_b.height > 0:
                aspect_a = info_a.width / info_a.height
                aspect_b = info_b.width / info_b.height
                if abs(aspect_a - aspect_b) / max(aspect_a, aspect_b) > 0.005:
                    self.log_line.emit(
                        "⚠️ Unterschiedliches Seitenverhältnis erkannt. Bei abweichendem Crop/Letterboxing "
                        "sind die Qualitätsmetriken nur eingeschränkt aussagekräftig."
                    )
        if info_a.hdr_label != "SDR" or info_b.hdr_label != "SDR":
            self.log_line.emit(
                "⚠️ HDR/Dolby-Vision erkannt: Der normale libvmaf-Filter ist hier nur als relativer "
                "Vergleichswert zu verstehen; die visuelle HDR-Wirkung wird damit nicht vollständig bewertet."
            )
        if info_a.frame_rate and info_b.frame_rate and info_a.frame_rate != info_b.frame_rate:
            self.log_line.emit(
                f"⚠️ Unterschiedliche Framerate: A {info_a.frame_rate}, B {info_b.frame_rate}. "
                "Framegenaue Metriken können dadurch weniger belastbar sein."
            )

        compare_duration = comparison_duration_limit(info_a.duration_s, info_b.duration_s, self.offset_b_s)
        if compare_duration < 1.0:
            self.log_line.emit("❌ Mit dem gewählten Offset bleibt keine gemeinsame Vergleichslaufzeit.")
            return

        segments = parse_quality_segments(
            self.manual_ranges,
            duration_s=compare_duration,
            default_duration_s=float(self.sample_duration_s),
        )
        if not segments:
            segments = automatic_quality_segments(
                duration_s=compare_duration,
                count=self.sample_count,
                segment_duration_s=float(self.sample_duration_s),
            )

        results: list[QualityComparisonResult] = []
        self.progress.emit(0)
        for idx, segment in enumerate(segments, start=1):
            if self._abort:
                self.log_line.emit("⚠️ Dateivergleich abgebrochen.")
                return
            start_a, start_b = comparison_segment_starts(segment.start_s, self.offset_b_s)
            duration = min(
                segment.duration_s,
                max(0.0, info_a.duration_s - start_a),
                max(0.0, info_b.duration_s - start_b),
            )
            if duration < 0.5:
                self.log_line.emit(f"⚠️ Segment {segment.label} ist zu kurz und wird übersprungen.")
                continue

            result = QualityComparisonResult(
                segment_label=segment.label,
                start_a_s=start_a,
                start_b_s=start_b,
                duration_s=duration,
            )
            self.log_line.emit(
                f"ℹ️  Segment {segment.label}: A {start_a:.3f}s / B {start_b:.3f}s / {duration:.1f}s"
            )
            result.ssim = self._measure_ssim(start_a, start_b, duration, info_b.width, info_b.height, result.notes)
            result.vmaf = self._measure_vmaf(start_a, start_b, duration, info_b.width, info_b.height, result.notes)
            results.append(result)
            self.result_ready.emit(result)
            self._log_result(result)
            self.progress.emit(int(idx / max(len(segments), 1) * 100))

        avg_ssim = self._average([item.ssim for item in results])
        avg_vmaf = self._average([item.vmaf for item in results])
        notes: list[str] = []
        if any(item.ssim is None for item in results):
            notes.append("SSIM war nicht für alle Segmente verfügbar.")
        if any(item.vmaf is None for item in results):
            notes.append("VMAF war nicht für alle Segmente verfügbar (FFmpeg/libvmaf prüfen).")
        assessment = quality_comparison_assessment(
            average_vmaf=avg_vmaf,
            average_ssim=avg_ssim,
            size_a_bytes=info_a.size_bytes,
            size_b_bytes=info_b.size_bytes,
        )
        summary = QualityComparisonSummary(
            file_a=info_a,
            file_b=info_b,
            average_ssim=avg_ssim,
            average_vmaf=avg_vmaf,
            compared_segments=len(results),
            assessment=assessment,
            notes=notes,
        )
        self.summary_ready.emit(summary)
        self.log_line.emit(f"📊 Ergebnis: {assessment}")
        if avg_ssim is not None or avg_vmaf is not None:
            ssim_text = f"{avg_ssim:.5f}" if avg_ssim is not None else "n/v"
            vmaf_text = f"{avg_vmaf:.2f}" if avg_vmaf is not None else "n/v"
            self.log_line.emit(f"📈 Mittelwerte: SSIM {ssim_text} | VMAF {vmaf_text}")
        self.progress.emit(100)

    @staticmethod
    def _average(values: list[float | None]) -> float | None:
        valid = [float(value) for value in values if value is not None]
        return sum(valid) / len(valid) if valid else None

    @staticmethod
    def _file_info(media, path: str) -> QualityFileInfo:
        video = getattr(media, "primary_video", None)
        if video is None:
            videos = getattr(media, "video_streams", []) or []
            video = videos[0] if videos else None
        hdr_label = "SDR"
        if bool(getattr(media, "has_dv", False)):
            hdr_label = "Dolby Vision"
        elif bool(getattr(media, "has_hdrplus", False)):
            hdr_label = "HDR10+"
        elif bool(getattr(media, "is_hdr", False)):
            hdr_label = "HDR"
        return QualityFileInfo(
            path=path,
            name=Path(path).name,
            size_bytes=int(getattr(media, "size_bytes", 0) or (Path(path).stat().st_size if Path(path).exists() else 0)),
            duration_s=float(getattr(media, "duration_s", 0.0) or 0.0),
            width=int(getattr(video, "width", 0) or 0),
            height=int(getattr(video, "height", 0) or 0),
            codec=str(getattr(video, "codec", "") or ""),
            pix_fmt=str(getattr(video, "pix_fmt", "") or ""),
            frame_rate=str(getattr(video, "frame_rate", "") or ""),
            hdr_label=hdr_label,
        )

    def _run_process(self, cmd: list[str], *, label: str) -> tuple[int, str, str]:
        result = run_tool(
            cmd,
            label=f"Qualitätsvergleich: {label}",
            timeout_s=get_timeout("quality_test_process"),
            worker=self,
            log=lambda message, _level="info": self.log_line.emit(message),
            abort_on_request=True,
        )
        if result.aborted or self._abort:
            raise RuntimeError("Abgebrochen")
        if result.timed_out:
            timeout = result.timeout_s
            if timeout is None:
                raise RuntimeError(f"{label} wurde wegen eines Timeouts beendet.")
            raise RuntimeError(f"{label} Timeout nach {float(timeout):.0f}s.")
        if not result.ok:
            raise RuntimeError(f"{label} fehlgeschlagen: {result.combined_output[:2000]}")
        return result.returncode, result.stdout, result.stderr

    @staticmethod
    def _metric_filter(metric: str, width: int, height: int) -> str:
        width = max(16, int(width or 1920))
        height = max(16, int(height or 1080))
        return (
            f"[0:v]settb=AVTB,setpts=PTS-STARTPTS,"
            f"scale={width}:{height}:flags=bicubic,format=yuv420p[ref];"
            f"[1:v]settb=AVTB,setpts=PTS-STARTPTS,"
            f"scale={width}:{height}:flags=bicubic,format=yuv420p[dist];"
            f"[dist][ref]{metric}"
        )

    def _metric_command(self, metric: str, start_a: float, start_b: float, duration: float, width: int, height: int) -> list[str]:
        return [
            str(self.tools.ffmpeg),
            "-hide_banner",
            "-nostats",
            "-v", "info",
            "-ss", f"{start_a:.6f}",
            "-i", self.file_a,
            "-ss", f"{start_b:.6f}",
            "-i", self.file_b,
            "-t", f"{duration:.6f}",
            "-filter_complex", self._metric_filter(metric, width, height),
            "-f", "null",
            "-",
        ]

    def _measure_ssim(self, start_a: float, start_b: float, duration: float, width: int, height: int, notes: list[str]) -> float | None:
        try:
            _rc, _out, err = self._run_process(
                self._metric_command("ssim", start_a, start_b, duration, width, height),
                label="SSIM A↔B",
            )
            match = re.search(r"All:([0-9.]+)", err or "")
            return float(match.group(1)) if match else None
        except Exception as exc:
            notes.append(f"SSIM nicht verfügbar: {str(exc)[:180]}")
            return None

    def _measure_vmaf(self, start_a: float, start_b: float, duration: float, width: int, height: int, notes: list[str]) -> float | None:
        try:
            _rc, _out, err = self._run_process(
                self._metric_command("libvmaf", start_a, start_b, duration, width, height),
                label="VMAF B gegen A",
            )
            match = re.search(r"VMAF score:\s*([0-9.]+)", err or "")
            return float(match.group(1)) if match else None
        except Exception as exc:
            notes.append(f"VMAF nicht verfügbar: {str(exc)[:180]}")
            return None

    def _log_result(self, result: QualityComparisonResult) -> None:
        ssim = f"{result.ssim:.5f}" if result.ssim is not None else "n/v"
        vmaf = f"{result.vmaf:.2f}" if result.vmaf is not None else "n/v"
        self.log_line.emit(f"✅ {result.segment_label}: SSIM {ssim} | VMAF {vmaf}")
        for note in result.notes:
            self.log_line.emit(f"⚠️  {note}")
