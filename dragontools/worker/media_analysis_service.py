# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..core.media_analyzer import analyze_media


class MediaAnalysisService:
    """Kapselt Medienanalyse inkl. Dauer/Dateigroesse und Warnungslogging."""

    def __init__(
        self,
        *,
        tools,
        probe_duration_ms: Callable[[str], int | None],
        log: Callable[[str, str], None],
    ) -> None:
        self._tools = tools
        self._probe_duration_ms = probe_duration_ms
        self._log = log

    def analyze(self, input_path: str) -> tuple[object, int | None, int]:
        media_info = analyze_media(input_path, self._tools)
        self.log_analysis_warnings(media_info)
        duration_ms = self._probe_duration_ms(input_path)
        src = Path(input_path)
        size_before = src.stat().st_size if src.exists() else 0
        return media_info, duration_ms, size_before

    def log_analysis_warnings(self, media_info) -> None:
        for warning in getattr(media_info, "analysis_warnings", []) or []:
            self._log(f"Analyse-Warnung: {warning}", "warn")
