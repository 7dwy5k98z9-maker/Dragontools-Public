# -*- coding: utf-8 -*-
"""Audio planning for the Dolby Vision remux pipeline."""
from __future__ import annotations

from collections.abc import Callable


AudioPlanBuilder = Callable[..., object]
AudioTitleBuilder = Callable[..., str]
AudioFilterBuilder = Callable[[object], str | None]


def build_dv_audio_jobs(
    worker,
    media_info,
    file_override: dict | None,
    *,
    plan_builder: AudioPlanBuilder,
    title_builder: AudioTitleBuilder,
    filter_builder: AudioFilterBuilder,
) -> list[dict]:
    """Translate the central audio plan into intermediate remux jobs."""
    container = str(getattr(worker, "container", "mp4") or "mp4").lower()
    plan = plan_builder(
        audio_streams=media_info.audio_streams,
        file_override=file_override,
        container=container,
    )
    jobs: list[dict] = []
    for decision in plan:
        chosen = decision.stream
        codec = decision.target_codec
        extension = _audio_extension(container, codec)
        common = {
            "stream_index": chosen.index,
            "codec": codec,
            "ext": extension,
            "language": (chosen.language or "und").lower(),
            "title": title_builder(
                language=chosen.language,
                codec=codec,
                channels=decision.target_channels,
                bitrate_bps=decision.target_bitrate,
            ),
        }
        if decision.needs_transcode:
            bitrate_k = max(
                1,
                int(decision.target_bitrate / 1000) if decision.target_bitrate else 256,
            )
            worker.log(
                f"  🔊 Audio #{chosen.index} ({chosen.codec}) -> "
                f"{codec} {decision.target_channels}ch {bitrate_k}k",
                "info",
            )
            jobs.append(
                {
                    **common,
                    "mode": "transcode",
                    "channels": decision.target_channels,
                    "bitrate_k": bitrate_k,
                    "filter_chain": filter_builder(decision),
                    "drc_scale": decision.drc_scale,
                }
            )
            continue

        worker.log(f"  🔊 Audio #{chosen.index} ({chosen.codec}) -> copy", "info")
        jobs.append({**common, "mode": "copy"})
    return jobs


def _audio_extension(container: str, codec: str) -> str:
    if container == "mkv":
        return ".mka"
    if codec == "eac3":
        return ".eac3"
    if codec == "ac3":
        return ".ac3"
    return ".m4a"
