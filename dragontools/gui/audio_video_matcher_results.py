# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox

from ..core.audio_video_matcher import (
    CutMatchResult,
    TimeMappingResult,
    format_seconds,
    preferred_german_audio_stream,
)


class AudioVideoMatcherResultsMixin:
    """Owns analysis state, result rendering and create eligibility."""

    def _analysis_ready(self, result: TimeMappingResult) -> None:
        self._analysis = result
        self._cut_results = []
        self._render_analysis(result)
        if result.mode == "C" and result.suspect_cut_ranges:
            self.cut_ranges.setText(
                ";".join(
                    f"{format_seconds(item.start_s)}-{format_seconds(item.end_s)}"
                    for item in result.suspect_cut_ranges
                )
            )
        self._set_running(False)

    def _cuts_ready(self, cuts: list[CutMatchResult]) -> None:
        self._cut_results = list(cuts or [])
        self._set_running(False)
        if self._analysis and any(not item.resolved for item in self._cut_results):
            QMessageBox.warning(
                self,
                "Schnittbereiche",
                "Mindestens ein Bereich enthält Zielinhalt ohne deutsche Audioentsprechung. "
                "Die automatische Erstellung bleibt blockiert.",
            )

    def _result_ready(self, output_path: str) -> None:
        QMessageBox.information(self, "Audio-Video-Matcher", f"Datei erstellt:\n{output_path}")

    def _render_analysis(self, result: TimeMappingResult) -> None:
        labels = {
            "A": "Fall A – Offset",
            "B": "Fall B – Drift",
            "C": "Fall C – Schnittunterschiede",
            "D": "Kein sicheres Match",
        }
        self.case_value.setText(labels.get(result.mode, result.mode))
        self.confidence_value.setText(f"{result.confidence_percent:.1f} %")
        self.offset_value.setText(f"{result.offset_s:+.3f} s")
        self.speed_value.setText(f"{result.speed_factor:.8f}")
        self.drift_value.setText(f"{result.drift_s:.3f} s")
        self.common_value.setText(
            f"{format_seconds(result.common_start_target_s)} – "
            f"{format_seconds(result.common_end_target_s)}"
        )
        self._render_audio_choice(result)

    def _render_audio_choice(self, result: TimeMappingResult) -> None:
        stream = preferred_german_audio_stream(result.source_info)
        self.audio_combo.clear()
        if stream is None:
            self.audio_combo.addItem("Keine Audiospur gefunden", None)
            return
        preferred_idx = 0
        for idx, audio in enumerate(result.source_info.audio_streams):
            lang = audio.language or "und"
            title = f" | {audio.title}" if audio.title else ""
            bitrate = f" | {int(audio.bitrate / 1000)} kbps" if audio.bitrate else ""
            self.audio_combo.addItem(
                f"#{audio.index} | {lang} | {audio.codec} | {audio.channels}ch{bitrate}{title}",
                int(audio.index),
            )
            if audio.index == stream.index:
                preferred_idx = idx
        self.audio_combo.setCurrentIndex(preferred_idx)

    def _selected_audio_index(self) -> int | None:
        value = self.audio_combo.currentData()
        try:
            return int(value)
        except Exception:
            return None

    def _can_create(self) -> bool:
        if self._analysis is None:
            return False
        if self._analysis.mode in {"A", "B"}:
            return bool(self._analysis.can_process)
        if self._analysis.mode == "C":
            return bool(self._cut_results) and all(item.resolved for item in self._cut_results)
        return False
