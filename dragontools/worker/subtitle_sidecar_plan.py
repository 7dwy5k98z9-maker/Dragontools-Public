# -*- coding: utf-8 -*-
"""Pure planning helpers for MP4 subtitle sidecar exports."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


@dataclass(frozen=True)
class SidecarSelection:
    plan: object
    storage: object
    streams: tuple[object, ...]

    @property
    def planned_stream_indices(self) -> tuple[int, ...]:
        return tuple(int(stream.index) for stream in self.streams)


@dataclass(frozen=True)
class SidecarTarget:
    stream: object
    language: str
    key: tuple[str, bool]
    number: int | None
    output_path: str


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
    if sidecars_enabled(subtitle_rules):
        streams = list(getattr(plan, "external_streams", ()) or ())
        burn_sub = getattr(plan, "burn_sub", None)
        if (
            preserve_burn_candidate
            and burn_sub is not None
            and all(int(stream.index) != int(burn_sub.index) for stream in streams)
        ):
            streams.insert(0, burn_sub)
    else:
        streams = list(getattr(storage, "external_streams", ()) or ())
    return SidecarSelection(plan=plan, storage=storage, streams=tuple(streams))


def build_sidecar_targets(
    streams: Iterable[object],
    output_base: str | Path,
    *,
    language_tag: Callable[[str | None], str],
    filename_builder: Callable[[Path, str, bool, str, int | None], str],
    codec_resolver: Callable[[str], tuple[str, list[str]] | tuple[str, tuple[str, ...]] | None],
) -> tuple[list[SidecarTarget], list[tuple[object, str, str]]]:
    """Build deterministic names; unsupported codecs are returned separately."""
    stream_list = list(streams)
    languages = [language_tag(getattr(stream, "language", None) or "und") for stream in stream_list]
    keys = [(language, bool(getattr(stream, "forced", False))) for language, stream in zip(languages, stream_list)]
    counts = Counter(keys)
    cursors: dict[tuple[str, bool], int] = {}
    base = Path(str(output_base))
    targets: list[SidecarTarget] = []
    unsupported: list[tuple[object, str, str]] = []

    for stream, language, key in zip(stream_list, languages, keys):
        codec = str(getattr(stream, "codec", "") or "").lower()
        codec_result = codec_resolver(codec)
        if codec_result is None:
            unsupported.append((stream, language, codec))
            continue
        ext, _codec_args = codec_result
        number = None
        if counts[key] > 1:
            number = cursors.get(key, 1)
            cursors[key] = number + 1
        targets.append(
            SidecarTarget(
                stream=stream,
                language=language,
                key=key,
                number=number,
                output_path=filename_builder(base, language, bool(getattr(stream, "forced", False)), ext, number),
            )
        )
    return targets, unsupported
