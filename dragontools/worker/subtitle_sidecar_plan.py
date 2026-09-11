# -*- coding: utf-8 -*-
"""Pure planning helpers for MP4 subtitle sidecar exports."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable


TEXT_TO_SRT_CODECS = {
    "ass",
    "ssa",
    "subrip",
    "srt",
    "subt",
    "mov_text",
    "tx3g",
    "text",
    "webvtt",
}


@dataclass(frozen=True)
class SidecarSelection:
    plan: object
    storage: object
    normal_streams: tuple[object, ...]
    ass_srt_streams: tuple[object, ...] = ()

    @property
    def streams(self) -> tuple[object, ...]:
        """Kompatibilitätsalias: alle Streams, die irgendein Sidecar-Ziel haben."""
        return dedupe_stream_objects((*self.normal_streams, *self.ass_srt_streams))

    @property
    def planned_stream_indices(self) -> tuple[int, ...]:
        return tuple(int(stream.index) for stream in self.streams)


def dedupe_stream_objects(streams: Iterable[object]) -> tuple[object, ...]:
    result: list[object] = []
    seen: set[int] = set()
    for stream in streams:
        try:
            index = int(stream.index)
        except Exception:
            index = id(stream)
        if index in seen:
            continue
        seen.add(index)
        result.append(stream)
    return tuple(result)


def _selected_streams(plan: object, *, preserve_burn_candidate: bool) -> list[object]:
    streams = list(getattr(plan, "external_streams", ()) or ())
    burn_sub = getattr(plan, "burn_sub", None)
    if (
        preserve_burn_candidate
        and burn_sub is not None
        and all(int(stream.index) != int(burn_sub.index) for stream in streams)
    ):
        streams.insert(0, burn_sub)
    return list(dedupe_stream_objects(streams))


def select_sidecar_streams(
    subtitle_streams: Iterable[object],
    *,
    audio_streams: Iterable[object],
    media_duration_s,
    file_override,
    subtitle_rules: dict,
    preserve_burn_candidate: bool,
    normalize_override: Callable,
    compute_plan: Callable,
    build_storage_plan: Callable,
    sidecars_enabled: Callable[[dict], bool],
    additional_sidecars_enabled: Callable[[dict], bool] | None = None,
    text_to_srt_sidecar_enabled: Callable[[dict], bool] | None = None,
    container: str = "mp4",
) -> SidecarSelection:
    """Resolve the rule plan and the streams that must become sidecars."""
    plan = compute_plan(
        list(subtitle_streams),
        audio_streams=list(audio_streams),
        file_override=normalize_override(file_override),
        subtitle_rules=subtitle_rules,
        container_copy_supported=True,
        media_duration_s=media_duration_s,
    )
    storage = build_storage_plan(
        plan,
        subtitle_rules=subtitle_rules,
        preserve_burn_candidate=preserve_burn_candidate,
    )
    target_container = str(container or "mkv").lower()
    selected = _selected_streams(plan, preserve_burn_candidate=preserve_burn_candidate)
    additional_enabled = (
        bool(additional_sidecars_enabled(subtitle_rules))
        if additional_sidecars_enabled is not None
        else False
    )
    text_srt_enabled = (
        bool(text_to_srt_sidecar_enabled(subtitle_rules))
        if text_to_srt_sidecar_enabled is not None
        else False
    )

    if target_container in {"mp4", "m4v", "mov"}:
        if sidecars_enabled(subtitle_rules) or additional_enabled:
            normal_streams = selected
        else:
            normal_streams = list(getattr(storage, "external_streams", ()) or ())
    else:
        normal_streams = selected if additional_enabled else []

    ass_srt_streams = [
        stream for stream in selected
        if text_srt_enabled and str(getattr(stream, "codec", "") or "").lower() in TEXT_TO_SRT_CODECS
    ]
    return SidecarSelection(
        plan=plan,
        storage=storage,
        normal_streams=dedupe_stream_objects(normal_streams),
        ass_srt_streams=dedupe_stream_objects(ass_srt_streams),
    )
