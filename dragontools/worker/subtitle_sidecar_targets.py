# -*- coding: utf-8 -*-
"""Zielpfad- und Codec-Planung fuer Untertitel-Sidecars."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from .subtitle_sidecar_plan import TEXT_TO_SRT_CODECS, dedupe_stream_objects


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


def _stream_index_set(streams: Iterable[object]) -> set[int]:
    return {int(stream.index) for stream in streams}


def _target_number(
    key: tuple[str, bool],
    counts: Counter[tuple[str, bool]],
    cursors: dict[tuple[str, bool], int],
) -> int | None:
    if counts[key] <= 1:
        return None
    number = cursors.get(key, 1)
    cursors[key] = number + 1
    return number


def _append_native_target(
    targets: list[SidecarTarget],
    unsupported: list[tuple[object, str, str]],
    *,
    stream: object,
    language: str,
    key: tuple[str, bool],
    number: int | None,
    base: Path,
    filename_builder: Callable[[Path, str, bool, str, int | None], str],
    codec_resolver: Callable[[str], tuple[str, list[str]] | tuple[str, tuple[str, ...]] | None],
) -> None:
    codec = str(getattr(stream, "codec", "") or "").lower()
    codec_result = codec_resolver(codec)
    if codec_result is None:
        unsupported.append((stream, language, codec))
        return
    ext, codec_args = codec_result
    targets.append(
        SidecarTarget(
            stream=stream,
            language=language,
            key=key,
            number=number,
            output_path=filename_builder(base, language, bool(getattr(stream, "forced", False)), ext, number),
            codec_args=tuple(str(arg) for arg in codec_args),
            output_codec=codec,
        )
    )


def _append_text_to_srt_target(
    targets: list[SidecarTarget],
    *,
    stream: object,
    language: str,
    key: tuple[str, bool],
    number: int | None,
    base: Path,
    filename_builder: Callable[[Path, str, bool, str, int | None], str],
) -> None:
    output_path = filename_builder(base, language, bool(getattr(stream, "forced", False)), ".srt", number)
    if any(target.output_path == output_path for target in targets):
        return
    targets.append(
        SidecarTarget(stream, language, key, number, output_path, ("-c:s", "srt"), "srt", "text_to_srt")
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
    normal_streams = dedupe_stream_objects(streams)
    ass_srt_selected = dedupe_stream_objects(
        stream for stream in ass_srt_streams
        if str(getattr(stream, "codec", "") or "").lower() in TEXT_TO_SRT_CODECS
    )
    stream_list = list(dedupe_stream_objects((*normal_streams, *ass_srt_selected)))
    normal_indices = _stream_index_set(normal_streams)
    ass_srt_indices = _stream_index_set(ass_srt_selected)
    languages = [language_tag(getattr(stream, "language", None) or "und") for stream in stream_list]
    keys = [(language, bool(getattr(stream, "forced", False))) for language, stream in zip(languages, stream_list)]
    counts = Counter(keys)
    cursors: dict[tuple[str, bool], int] = {}
    targets: list[SidecarTarget] = []
    unsupported: list[tuple[object, str, str]] = []

    for stream, language, key in zip(stream_list, languages, keys):
        number = _target_number(key, counts, cursors)
        if int(stream.index) in normal_indices:
            _append_native_target(
                targets,
                unsupported,
                stream=stream,
                language=language,
                key=key,
                number=number,
                base=Path(str(output_base)),
                filename_builder=filename_builder,
                codec_resolver=codec_resolver,
            )
        if int(stream.index) in ass_srt_indices:
            _append_text_to_srt_target(
                targets,
                stream=stream,
                language=language,
                key=key,
                number=number,
                base=Path(str(output_base)),
                filename_builder=filename_builder,
            )
    return targets, unsupported
