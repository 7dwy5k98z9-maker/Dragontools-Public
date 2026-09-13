from __future__ import annotations

from pathlib import Path

from ..core.media_analyzer import analyze_media
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


class QualityCompareService:
    def __init__(self, *, tools, metrics, log, progress, result_ready, summary_ready, is_aborted) -> None:
        self._tools = tools
        self._metrics = metrics
        self._log = log
        self._progress = progress
        self._result_ready = result_ready
        self._summary_ready = summary_ready
        self._is_aborted = is_aborted

    def run(self, *, file_a: str, file_b: str, sample_count: int, sample_duration_s: int,
            manual_ranges: str, offset_b_s: float) -> None:
        if not self._validate_inputs(file_a, file_b, offset_b_s):
            return
        info_a = self.file_info(analyze_media(file_a, self._tools), file_a)
        info_b = self.file_info(analyze_media(file_b, self._tools), file_b)
        if not self._validate_media(info_a, info_b):
            return
        self._log_media_warnings(info_a, info_b)
        compare_duration = comparison_duration_limit(info_a.duration_s, info_b.duration_s, offset_b_s)
        if compare_duration < 1.0:
            self._log("❌ Mit dem gewählten Offset bleibt keine gemeinsame Vergleichslaufzeit.")
            return
        segments = parse_quality_segments(manual_ranges, duration_s=compare_duration, default_duration_s=float(sample_duration_s))
        if not segments:
            segments = automatic_quality_segments(duration_s=compare_duration, count=sample_count, segment_duration_s=float(sample_duration_s))
        results = self._compare_segments(file_a, file_b, info_a, info_b, segments, offset_b_s)
        if self._is_aborted():
            return
        self._emit_summary(info_a, info_b, results)
        self._progress(100)

    def _validate_inputs(self, file_a: str, file_b: str, offset_b_s: float) -> bool:
        if file_a == file_b:
            self._log("⚠️ Datei A und Datei B sind identisch.")
            return False
        if not Path(file_a).is_file() or not Path(file_b).is_file():
            self._log("❌ Eine der beiden Vergleichsdateien existiert nicht.")
            return False
        self._log(f"▶ Referenz A: {Path(file_a).name}")
        self._log(f"▶ Kandidat B: {Path(file_b).name}")
        if abs(offset_b_s) > 0.0005:
            self._log(f"ℹ️  Zeitversatz B: {offset_b_s:+.3f}s")
        return True

    def _validate_media(self, info_a: QualityFileInfo, info_b: QualityFileInfo) -> bool:
        if info_a.duration_s <= 0 or info_b.duration_s <= 0:
            self._log("❌ Laufzeit konnte für mindestens eine Datei nicht bestimmt werden.")
            return False
        delta = abs(info_a.duration_s - info_b.duration_s)
        if delta > max(1.0, min(info_a.duration_s, info_b.duration_s) * 0.005):
            self._log(f"⚠️ Laufzeiten unterscheiden sich um {delta:.3f}s. Bei abweichendem Schnitt oder Intro sind SSIM/VMAF ohne passenden Offset nicht aussagekräftig.")
        return True

    def _log_media_warnings(self, a: QualityFileInfo, b: QualityFileInfo) -> None:
        if (a.width, a.height) != (b.width, b.height):
            self._log(f"ℹ️  Unterschiedliche Auflösung: A {a.width}×{a.height}, B {b.width}×{b.height}. Für die Metrik wird A auf B-Auflösung skaliert.")
            if a.width > 0 and a.height > 0 and b.width > 0 and b.height > 0:
                aspect_a, aspect_b = a.width / a.height, b.width / b.height
                if abs(aspect_a - aspect_b) / max(aspect_a, aspect_b) > 0.005:
                    self._log("⚠️ Unterschiedliches Seitenverhältnis erkannt. Bei abweichendem Crop/Letterboxing sind die Qualitätsmetriken nur eingeschränkt aussagekräftig.")
        if a.hdr_label != "SDR" or b.hdr_label != "SDR":
            self._log("⚠️ HDR/Dolby-Vision erkannt: Der normale libvmaf-Filter ist hier nur als relativer Vergleichswert zu verstehen; die visuelle HDR-Wirkung wird damit nicht vollständig bewertet.")
        if a.frame_rate and b.frame_rate and a.frame_rate != b.frame_rate:
            self._log(f"⚠️ Unterschiedliche Framerate: A {a.frame_rate}, B {b.frame_rate}. Framegenaue Metriken können dadurch weniger belastbar sein.")

    def _compare_segments(self, file_a, file_b, info_a, info_b, segments, offset_b_s):
        results: list[QualityComparisonResult] = []
        self._progress(0)
        for idx, segment in enumerate(segments, start=1):
            if self._is_aborted():
                self._log("⚠️ Dateivergleich abgebrochen.")
                return results
            start_a, start_b = comparison_segment_starts(segment.start_s, offset_b_s)
            duration = min(segment.duration_s, max(0.0, info_a.duration_s - start_a), max(0.0, info_b.duration_s - start_b))
            if duration < 0.5:
                self._log(f"⚠️ Segment {segment.label} ist zu kurz und wird übersprungen.")
                continue
            result = QualityComparisonResult(segment_label=segment.label, start_a_s=start_a, start_b_s=start_b, duration_s=duration)
            self._log(f"ℹ️  Segment {segment.label}: A {start_a:.3f}s / B {start_b:.3f}s / {duration:.1f}s")
            result.ssim = self._metrics.measure_comparison(metric="ssim", file_a=file_a, file_b=file_b, start_a=start_a, start_b=start_b, duration=duration, width=info_b.width, height=info_b.height, label="SSIM A↔B", notes=result.notes)
            result.vmaf = self._metrics.measure_comparison(metric="libvmaf", file_a=file_a, file_b=file_b, start_a=start_a, start_b=start_b, duration=duration, width=info_b.width, height=info_b.height, label="VMAF B gegen A", notes=result.notes)
            results.append(result)
            self._result_ready(result)
            self.log_result(result)
            self._progress(int(idx / max(len(segments), 1) * 100))
        return results

    def _emit_summary(self, info_a, info_b, results) -> None:
        avg_ssim = self.average([item.ssim for item in results])
        avg_vmaf = self.average([item.vmaf for item in results])
        notes = []
        if any(item.ssim is None for item in results): notes.append("SSIM war nicht für alle Segmente verfügbar.")
        if any(item.vmaf is None for item in results): notes.append("VMAF war nicht für alle Segmente verfügbar (FFmpeg/libvmaf prüfen).")
        assessment = quality_comparison_assessment(average_vmaf=avg_vmaf, average_ssim=avg_ssim, size_a_bytes=info_a.size_bytes, size_b_bytes=info_b.size_bytes)
        summary = QualityComparisonSummary(file_a=info_a, file_b=info_b, average_ssim=avg_ssim, average_vmaf=avg_vmaf, compared_segments=len(results), assessment=assessment, notes=notes)
        self._summary_ready(summary)
        self._log(f"📊 Ergebnis: {assessment}")
        if avg_ssim is not None or avg_vmaf is not None:
            ssim_text = f"{avg_ssim:.5f}" if avg_ssim is not None else "n/v"
            vmaf_text = f"{avg_vmaf:.2f}" if avg_vmaf is not None else "n/v"
            self._log(f"📈 Mittelwerte: SSIM {ssim_text} | VMAF {vmaf_text}")

    @staticmethod
    def average(values: list[float | None]) -> float | None:
        valid = [float(value) for value in values if value is not None]
        return sum(valid) / len(valid) if valid else None

    @staticmethod
    def file_info(media, path: str) -> QualityFileInfo:
        video = getattr(media, "primary_video", None)
        if video is None:
            videos = getattr(media, "video_streams", []) or []
            video = videos[0] if videos else None
        hdr_label = "Dolby Vision" if bool(getattr(media, "has_dv", False)) else "HDR10+" if bool(getattr(media, "has_hdrplus", False)) else "HDR" if bool(getattr(media, "is_hdr", False)) else "SDR"
        return QualityFileInfo(
            path=path, name=Path(path).name,
            size_bytes=int(getattr(media, "size_bytes", 0) or (Path(path).stat().st_size if Path(path).exists() else 0)),
            duration_s=float(getattr(media, "duration_s", 0.0) or 0.0),
            width=int(getattr(video, "width", 0) or 0), height=int(getattr(video, "height", 0) or 0),
            codec=str(getattr(video, "codec", "") or ""), pix_fmt=str(getattr(video, "pix_fmt", "") or ""),
            frame_rate=str(getattr(video, "frame_rate", "") or ""), hdr_label=hdr_label,
        )

    def log_result(self, result: QualityComparisonResult) -> None:
        ssim = f"{result.ssim:.5f}" if result.ssim is not None else "n/v"
        vmaf = f"{result.vmaf:.2f}" if result.vmaf is not None else "n/v"
        self._log(f"✅ {result.segment_label}: SSIM {ssim} | VMAF {vmaf}")
        for note in result.notes: self._log(f"⚠️  {note}")
