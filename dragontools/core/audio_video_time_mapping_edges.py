# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field

from .audio_video_match_models import AudioVideoMatcherSettings, VideoInfo


@dataclass(slots=True)
class EdgeMapping:
    common_start_target_s: float
    common_end_target_s: float
    source_extra_start_s: float
    source_extra_end_s: float
    target_extra_start_s: float
    target_extra_end_s: float
    warnings: list[str] = field(default_factory=list)


def evaluate_edges(
    *,
    source_info: VideoInfo,
    target_info: VideoInfo,
    offset_s: float,
    speed_factor: float,
    settings: AudioVideoMatcherSettings,
) -> EdgeMapping:
    source_at_target_start = offset_s
    source_at_target_end = speed_factor * float(target_info.duration_s or 0.0) + offset_s
    source_duration = float(source_info.duration_s or 0.0)
    target_duration = float(target_info.duration_s or 0.0)
    safe_speed = max(speed_factor, 0.001)

    source_extra_start = max(0.0, source_at_target_start)
    source_extra_end = max(0.0, source_duration - source_at_target_end)
    target_extra_start = max(0.0, -source_at_target_start / safe_speed)
    target_extra_end = max(0.0, (source_at_target_end - source_duration) / safe_speed)
    common_start = target_extra_start if target_extra_start > settings.edge_extra_warn_s else 0.0
    common_end = max(common_start, target_duration - target_extra_end)

    warnings = _edge_warnings(
        source_extra_start=source_extra_start,
        source_extra_end=source_extra_end,
        target_extra_start=target_extra_start,
        target_extra_end=target_extra_end,
        threshold=settings.edge_extra_warn_s,
    )
    return EdgeMapping(
        common_start,
        common_end,
        source_extra_start,
        source_extra_end,
        target_extra_start,
        target_extra_end,
        warnings,
    )


def _edge_warnings(*, source_extra_start: float, source_extra_end: float, target_extra_start: float, target_extra_end: float, threshold: float) -> list[str]:
    warnings: list[str] = []
    if source_extra_start > threshold:
        warnings.append(f"Deutsche Quelle besitzt ca. {source_extra_start:.1f}s zusätzlich vor dem gemeinsamen Inhalt. Das ist Fall A/B und wird beim Audio getrimmt.")
    if source_extra_end > threshold:
        warnings.append(f"Deutsche Quelle besitzt ca. {source_extra_end:.1f}s zusätzlich nach dem gemeinsamen Inhalt. Das Zielvideo definiert die finale Länge; die Audiospur wird am Ende zugeschnitten.")
    if target_extra_start > threshold:
        warnings.append(f"Das Zielvideo enthält am Anfang ca. {target_extra_start:.1f}s zusätzlichen Inhalt ohne deutsche Audioentsprechung.")
    if target_extra_end > threshold:
        warnings.append(f"Das Zielvideo enthält am Ende ca. {target_extra_end:.1f}s zusätzlichen Inhalt, für den keine deutsche Audioentsprechung gefunden wurde.")
    return warnings
