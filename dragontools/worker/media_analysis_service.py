# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..core.media_analyzer import analyze_media
from ..core.media_duration import positive_seconds


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
        if not bool(getattr(media_info, "ffmpeg_stream_indices_trusted", True)):
            raise RuntimeError(
                "ffprobe lieferte keine verlässlichen globalen Streamindizes. "
                "DragonTools bricht die Konvertierung ab, statt MediaInfo-StreamOrder "
                "fälschlich als ffmpeg -map Index zu verwenden."
            )
        if getattr(media_info, "primary_video", None) is None:
            raise RuntimeError("Die Medienanalyse lieferte keine verarbeitbare Videospur.")
        duration_s = positive_seconds(getattr(media_info, "duration_s", None))
        duration_ms = (
            int(duration_s * 1000)
            if duration_s is not None and duration_s < 1_000_000
            else self._probe_duration_ms(input_path)
        )
        src = Path(input_path)
        size_before = src.stat().st_size if src.exists() else 0
        return media_info, duration_ms, size_before

    def log_analysis_warnings(self, media_info) -> None:
        for warning in getattr(media_info, "analysis_warnings", []) or []:
            self._log(f"Analyse-Warnung: {warning}", "warn")
