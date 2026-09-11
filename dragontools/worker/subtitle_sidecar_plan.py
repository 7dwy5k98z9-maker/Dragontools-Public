# -*- coding: utf-8 -*-
"""Pure planning helpers for MP4 subtitle sidecar exports."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
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
        return _dedupe_stream_objects((*self.normal_streams, *self.ass_srt_streams))

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
    codec_args: tuple[str, ...]
    output_codec: str
    variant: str = "native"


def _dedupe_stream_objects(streams: Iterable[object]) -> tuple[object, ...]:
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
    return list(_dedupe_stream_objects(streams))


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
        normal_streams=_dedupe_stream_objects(normal_streams),
        ass_srt_streams=_dedupe_stream_objects(ass_srt_streams),
    )


def build_sidecar_targets(
    streams: Iterable[object],
    output_base: str | Path,
    *,
    ass_srt_streams: Iterable[object] = (),
    language_tag: Callable[[str | None], str],
    filename_builder: Callable[[Path, str, bool, str, int | None], str],
    codec_resolver: Callable[[str], tuple[str, list[str]] | tuple[str, tuple[str, ...]] | None],
) -> tuple[list[SidecarTarget], list[tuple[object, str, str]]]:
    """Build deterministic names; unsupported codecs are returned separately."""
    normal_streams = _dedupe_stream_objects(streams)
    ass_srt_selected = _dedupe_stream_objects(
        stream for stream in ass_srt_streams
        if str(getattr(stream, "codec", "") or "").lower() in TEXT_TO_SRT_CODECS
    )
    stream_list = list(_dedupe_stream_objects((*normal_streams, *ass_srt_selected)))
    normal_indices = {int(stream.index) for stream in normal_streams}
    ass_srt_indices = {int(stream.index) for stream in ass_srt_selected}
    languages = [language_tag(getattr(stream, "language", None) or "und") for stream in stream_list]
    keys = [(language, bool(getattr(stream, "forced", False))) for language, stream in zip(languages, stream_list)]
    counts = Counter(keys)
    cursors: dict[tuple[str, bool], int] = {}
    base = Path(str(output_base))
    targets: list[SidecarTarget] = []
    unsupported: list[tuple[object, str, str]] = []

    for stream, language, key in zip(stream_list, languages, keys):
        codec = str(getattr(stream, "codec", "") or "").lower()
        number = None
        if counts[key] > 1:
            number = cursors.get(key, 1)
            cursors[key] = number + 1
        if int(stream.index) in normal_indices:
            codec_result = codec_resolver(codec)
            if codec_result is None:
                unsupported.append((stream, language, codec))
            else:
                ext, codec_args = codec_result
                output_path = filename_builder(
                    base, language, bool(getattr(stream, "forced", False)), ext, number
                )
                targets.append(
                    SidecarTarget(
                        stream=stream,
                        language=language,
                        key=key,
                        number=number,
                        output_path=output_path,
                        codec_args=tuple(str(arg) for arg in codec_args),
                        output_codec=codec,
                    )
                )
        if int(stream.index) in ass_srt_indices:
            output_path = filename_builder(
                base, language, bool(getattr(stream, "forced", False)), ".srt", number
            )
            if not any(target.output_path == output_path for target in targets):
                targets.append(
                    SidecarTarget(
                        stream=stream,
                        language=language,
                        key=key,
                        number=number,
                        output_path=output_path,
                        codec_args=("-c:s", "srt"),
                        output_codec="srt",
                        variant="text_to_srt",
                    )
                )
    return targets, unsupported
