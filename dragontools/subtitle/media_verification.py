"""Actual stream inventories and subtitle mux contracts; all probes are owned."""

import json
from dataclasses import dataclass
from pathlib import Path

from ..core.lang_codes import mkv_language_tags
from ..core.media_hdr_detection import detect_hdr_from_ffprobe_stream
from ..worker.media_contract import _audio_codec_family, _subtitle_codec_family
from ..worker.media_contract_types import (
    ExpectedAudioTrack,
    ExpectedMediaContract,
    ExpectedSubtitleTrack,
)
from ..worker.output_contract_tracks import (
    compare_audio_tracks,
    compare_subtitle_tracks,
)
from ..worker.tool_runner import run_tool
from .output_safety import stopped, valid_stream_indices


def probe_streams(path, *, ffprobe, worker=None, logger=None, count_packets=False):
    args = ["-count_packets", "-select_streams", "s"] if count_packets else []
    result = run_tool(
        [
            ffprobe,
            "-v",
            "error",
            *args,
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        label="Untertitel-Medienprüfung",
        timeout_s=60,
        worker=worker,
        log=(lambda message, _level="info": logger(message)) if logger else None,
    )
    if result.returncode != 0 or stopped(result, worker):
        raise ValueError("Untertitel-Medienprüfung fehlgeschlagen oder abgebrochen.")
    payload = json.loads(result.stdout)
    rows = payload.get("streams")
    valid_stream_indices(rows)
    if not rows or any(
        not row.get("codec_type") or not row.get("codec_name") for row in rows
    ):
        raise ValueError("Medienprüfung enthält keine vollständigen Spuren.")
    for row in rows:
        tags = dict(row.get("tags") or {})
        tags["title"] = tags.get("title") or tags.get("handler_name") or ""
        row["tags"] = tags
    return rows


def _of_type(rows, kind):
    return [row for row in rows if row["codec_type"] == kind]


def _audio(row):
    tags, flags = row.get("tags") or {}, row.get("disposition") or {}
    return ExpectedAudioTrack(
        _audio_codec_family(row["codec_name"]),
        int(row.get("channels") or 0),
        tags.get("language", ""),
        bool(flags.get("default")),
        tags.get("title") or None,
        bool(flags.get("forced")),
    )


def _subtitle(row):
    tags, flags = row.get("tags") or {}, row.get("disposition") or {}
    return ExpectedSubtitleTrack(
        _subtitle_codec_family(row["codec_name"]),
        tags.get("language", ""),
        bool(flags.get("forced")),
        bool(flags.get("default")),
        tags.get("title") or None,
    )


@dataclass(frozen=True)
class SubtitleInjectionPlan:
    source_streams: tuple[dict, ...]
    contract: ExpectedMediaContract
    new_subtitle_index: int


def build_injection_plan(
    video_path,
    sub_path,
    *,
    output_path,
    ffprobe,
    language,
    forced,
    title,
    subtitle_codec=None,
    map_existing_subtitles=True,
    existing_subtitle_count=None,
    worker=None,
    logger=None,
):
    source = probe_streams(video_path, ffprobe=ffprobe, worker=worker, logger=logger)
    subtitles = probe_streams(sub_path, ffprobe=ffprobe, worker=worker, logger=logger)
    if len(subtitles) != 1 or subtitles[0]["codec_type"] != "subtitle":
        raise ValueError(
            "Die zusätzliche Datei muss genau eine Untertitelspur enthalten."
        )
    videos = _of_type(source, "video")
    if not videos:
        raise ValueError("Die Quelle enthält keine Videospur.")
    old_subs = _of_type(source, "subtitle") if map_existing_subtitles else []
    if existing_subtitle_count is not None:
        if type(existing_subtitle_count) is not int or existing_subtitle_count != len(
            old_subs
        ):
            raise ValueError(
                "Untertitelanzahl stimmt nicht mit dem aktuellen Medieninventar überein."
            )
    new = ExpectedSubtitleTrack(
        _subtitle_codec_family(subtitle_codec or subtitles[0]["codec_name"]),
        mkv_language_tags(language)[0],
        bool(forced),
        False,
        title,
    )
    contract = ExpectedMediaContract(
        Path(output_path).suffix.lower().lstrip("."),
        videos[0]["codec_name"],
        len(videos),
        tuple(_audio(row) for row in _of_type(source, "audio")),
        tuple(_subtitle(row) for row in old_subs) + (new,),
    )
    return SubtitleInjectionPlan(tuple(source), contract, len(old_subs))


def _video_signature(row):
    return (
        row["codec_name"],
        row.get("width"),
        row.get("height"),
        row.get("pix_fmt"),
        row.get("color_transfer"),
        row.get("color_primaries"),
        bool((row.get("disposition") or {}).get("attached_pic")),
        detect_hdr_from_ffprobe_stream(row),
    )


def verify_injection(stage, plan, *, ffprobe, worker=None, logger=None):
    rows = probe_streams(stage, ffprobe=ffprobe, worker=worker, logger=logger)
    source_videos = [
        _video_signature(row) for row in _of_type(plan.source_streams, "video")
    ]
    actual_videos = [_video_signature(row) for row in _of_type(rows, "video")]
    errors = compare_audio_tracks(plan.contract, _of_type(rows, "audio"))
    errors.extend(compare_subtitle_tracks(plan.contract, _of_type(rows, "subtitle")))
    if source_videos != actual_videos:
        errors.append(
            "Videoanzahl, Codec, Geometrie oder HDR-Eigenschaften wurden verändert."
        )
    for kind in ("attachment", "data"):
        if len(_of_type(rows, kind)) != len(_of_type(plan.source_streams, kind)):
            errors.append(f"{kind}-Spuren wurden verändert.")
    if errors:
        raise ValueError("; ".join(errors))
    return True


def verify_subtitle_export(stage, *, expected_codec, ffprobe, worker=None, logger=None):
    # Inspect all stream kinds so an unexpected video cannot disappear behind
    # a subtitle-only selector. Count packets in a separate subtitle probe.
    rows = probe_streams(stage, ffprobe=ffprobe, worker=worker, logger=logger)
    if len(rows) != 1 or rows[0]["codec_type"] != "subtitle":
        raise ValueError("Sidecar enthält nicht genau eine Untertitelspur.")
    if _subtitle_codec_family(rows[0]["codec_name"]) != _subtitle_codec_family(
        expected_codec
    ):
        raise ValueError("Sidecar enthält den falschen Untertitelcodec.")
    counted = probe_streams(
        stage, ffprobe=ffprobe, worker=worker, logger=logger, count_packets=True
    )
    if len(counted) != 1 or int(counted[0].get("nb_read_packets") or 0) < 1:
        raise ValueError("Sidecar enthält keine lesbaren Untertitelpakete.")
    return True


def verify_extraction(
    stage, *, input_path, stream_index, codec_args, ffprobe, worker=None, logger=None
):
    source = probe_streams(input_path, ffprobe=ffprobe, worker=worker, logger=logger)
    selected = [
        row
        for row in source
        if row["index"] == stream_index and row["codec_type"] == "subtitle"
    ]
    if len(selected) != 1:
        raise ValueError("Gewählter Stream ist keine eindeutige Untertitelspur.")
    codec = selected[0]["codec_name"]
    for index, arg in enumerate(codec_args[:-1]):
        if arg in {"-c", "-c:s", "-codec:s"} and codec_args[index + 1] != "copy":
            codec = codec_args[index + 1]
    return verify_subtitle_export(
        stage, expected_codec=codec, ffprobe=ffprobe, worker=worker, logger=logger
    )
