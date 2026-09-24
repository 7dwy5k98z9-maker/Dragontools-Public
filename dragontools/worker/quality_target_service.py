# -*- coding: utf-8 -*-
from __future__ import annotations

import statistics
import tempfile
from pathlib import Path

from ..core.quality_target import QualityTargetConfig, QualityTargetEvaluation, QualityTargetResult, adaptive_quality_search
from ..core.quality_tester import automatic_quality_segments
from ..core.sdr_hdr_enhancement import decide_sdr_hdr_enhancement
from .encoder_args import _scale, _vid_args


class AutomaticQualityTargetService:
    """Ermittelt optional einen per VMAF abgesicherten CQ/CRF/QP-Wert für eine Datei."""

    def __init__(self, *, tools, process_runner, metrics, log, is_aborted) -> None:
        self._tools = tools
        self._runner = process_runner
        self._metrics = metrics
        self._log = log
        self._is_aborted = is_aborted

    @staticmethod
    def quality_label(options: dict) -> str:
        return {"nvenc": "CQ", "qsv": "Q", "amf": "QP"}.get(
            str(options.get("encoder", "cpu")).lower(), "CRF"
        )

    @staticmethod
    def options_for_quality(options: dict, value: int) -> dict:
        updated = dict(options or {})
        encoder = str(updated.get("encoder", "cpu")).lower()
        if encoder == "nvenc":
            updated["cq"] = int(value)
        elif encoder == "qsv":
            updated["q"] = int(value)
        elif encoder == "amf":
            updated["qp"] = int(value)
        else:
            updated["crf"] = int(value)
        return updated

    @staticmethod
    def _is_hdr(media_info) -> bool:
        if bool(getattr(media_info, "is_hdr", False)):
            return True
        if bool(getattr(media_info, "has_dv", False)) or bool(getattr(media_info, "has_hdrplus", False)):
            return True
        video = getattr(media_info, "primary_video", None)
        transfer = str(getattr(video, "color_transfer", "") or "").strip().lower()
        return transfer in {"smpte2084", "pq", "arib-std-b67", "hlg"}

    def resolve(
        self,
        *,
        input_path: str,
        media_info,
        codec: str,
        fixed_quality: int,
        preset: str,
        encoder_options: dict,
        scale_mode: str,
    ) -> QualityTargetResult:
        config = QualityTargetConfig.from_encoder_options(encoder_options)
        result = QualityTargetResult(attempted=config.enabled)
        if not config.enabled:
            result.reason = "deaktiviert"
            return result
        enhancement = decide_sdr_hdr_enhancement(
            media_info, target_codec=codec, encoder_options=encoder_options
        )
        if enhancement.applied:
            result.reason = "SDR→HDR Enhancement wird nicht gegen die unveränderte SDR-Quelle per VMAF optimiert."
            self._log(
                f"🎯 Auto-Qualitätsziel übersprungen: SDR→HDR Enhancement nutzt weiterhin den festen "
                f"{self.quality_label(encoder_options)}-Wert {fixed_quality}.",
                "info",
            )
            return result
        if self._is_hdr(media_info):
            result.reason = "HDR/Dolby-Vision/HLG wird mit normalem libvmaf nicht automatisch bewertet."
            self._log(
                f"🎯 Auto-Qualitätsziel übersprungen: HDR/DV/HLG nutzt weiterhin den festen "
                f"{self.quality_label(encoder_options)}-Wert {fixed_quality}.",
                "info",
            )
            return result
        if self._is_aborted():
            result.reason = "abgebrochen"
            return result

        duration = float(getattr(media_info, "duration_s", 0.0) or 0.0)
        if duration <= 0:
            result.reason = "Quelllaufzeit unbekannt; feste Qualität bleibt aktiv."
            self._log(
                f"⚠️ Auto-Qualitätsziel: Quelllaufzeit unbekannt; fester "
                f"{self.quality_label(encoder_options)}-Wert {fixed_quality} bleibt aktiv.",
                "warn",
            )
            return result
        segments = automatic_quality_segments(
            duration_s=duration,
            count=config.sample_count,
            segment_duration_s=config.sample_duration_s,
        )
        label = self.quality_label(encoder_options)
        self._log(
            f"🎯 Auto-Qualitätsziel: VMAF ≥ {config.target_vmaf:.1f}, {config.sample_count}×{config.sample_duration_s:.0f}s, "
            f"{label} {config.min_quality}–{config.max_quality}.",
            "info",
        )

        measured: dict[int, QualityTargetEvaluation] = {}
        unavailable = False
        with tempfile.TemporaryDirectory(prefix="dragontools-vmaf-") as tmp:
            temp_root = Path(tmp)

            def evaluate(value: int) -> float | None:
                nonlocal unavailable
                if self._is_aborted():
                    raise RuntimeError("Abgebrochen")
                scores: list[float] = []
                for idx, segment in enumerate(segments, start=1):
                    output = temp_root / f"q{value:02d}_{idx:02d}.mkv"
                    self._encode_segment(
                        input_path=input_path,
                        output_path=str(output),
                        segment=segment,
                        codec=codec,
                        quality=value,
                        preset=preset,
                        encoder_options=encoder_options,
                        scale_mode=scale_mode,
                    )
                    try:
                        score = self._measure_vmaf(input_path, str(output), segment)
                    finally:
                        try:
                            output.unlink(missing_ok=True)
                        except OSError:
                            pass
                    if score is None:
                        unavailable = True
                        return None
                    scores.append(score)
                average = statistics.fmean(scores)
                measured[value] = QualityTargetEvaluation(value, average, tuple(scores))
                score_text = ", ".join(f"{score:.1f}" for score in scores)
                self._log(f"🔬 {label} {value}: Ø VMAF {average:.2f} ({score_text})", "info")
                return average

            try:
                selected, _basic_evaluations, target_met = adaptive_quality_search(
                    min_quality=config.min_quality,
                    max_quality=config.max_quality,
                    target_vmaf=config.target_vmaf,
                    evaluate=evaluate,
                )
            except RuntimeError as exc:
                result.reason = str(exc)
                return result

        result.evaluations = sorted(measured.values(), key=lambda item: item.quality)
        if selected is None:
            result.reason = (
                f"VMAF nicht verfügbar; fester {label}-Wert {fixed_quality} bleibt aktiv."
                if unavailable
                else f"VMAF-Ziel wurde im konfigurierten Bereich nicht erreicht; fester {label}-Wert {fixed_quality} bleibt aktiv."
            )
            self._log(f"⚠️ Auto-Qualitätsziel: {result.reason}", "warn")
            return result

        selected_eval = measured.get(selected)
        result.applied = True
        result.target_met = bool(target_met)
        result.selected_quality = selected
        result.selected_vmaf = selected_eval.average_vmaf if selected_eval else None
        result.reason = "Ziel erreicht"
        score = f" bei Ø VMAF {result.selected_vmaf:.2f}" if result.selected_vmaf is not None else ""
        self._log(f"✅ Auto-Qualitätsziel: {label} {selected}{score} gewählt.", "success")
        return result

    def _encode_segment(
        self,
        *,
        input_path: str,
        output_path: str,
        segment,
        codec: str,
        quality: int,
        preset: str,
        encoder_options: dict,
        scale_mode: str,
    ) -> None:
        options = self.options_for_quality(encoder_options, quality)
        args = _vid_args(codec, quality, preset, options)
        scale_filter = _scale(scale_mode)
        if scale_filter:
            args = ["-vf", scale_filter] + args
        cmd = [
            str(self._tools.ffmpeg), "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{segment.start_s:.3f}", "-t", f"{segment.duration_s:.3f}", "-i", input_path,
            "-map", "0:v:0", "-an", "-sn", *args, output_path,
        ]
        self._runner.run(cmd, label=f"VMAF-Testencode Q{quality}")

    def _measure_vmaf(self, input_path: str, output_path: str, segment) -> float | None:
        notes: list[str] = []
        dimensions = self._probe_dimensions(output_path)
        if dimensions is None:
            self._log("⚠️ VMAF-Testprobe fehlgeschlagen; Auto-Qualitätsziel bleibt beim festen Wert.", "warn")
            return None
        width, height = dimensions
        value = self._metrics.measure_encoded(
            metric="libvmaf",
            input_path=input_path,
            output_path=output_path,
            start_s=segment.start_s,
            duration_s=segment.duration_s,
            width=width,
            height=height,
            label="VMAF-Zielsuche",
            notes=notes,
        )
        for note in notes:
            self._log(f"⚠️ {note}", "warn")
        return value

    def _probe_dimensions(self, output_path: str) -> tuple[int, int] | None:
        cmd = [
            str(self._tools.ffprobe), "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", output_path,
        ]
        try:
            _rc, stdout, _stderr = self._runner.run(cmd, label="VMAF-Testprobe")
            width_text, height_text = str(stdout or "").strip().split("x", 1)
            return max(16, int(width_text)), max(16, int(height_text))
        except (RuntimeError, ValueError, TypeError):
            return None
