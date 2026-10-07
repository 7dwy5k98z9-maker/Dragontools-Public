# -*- coding: utf-8 -*-
"""Execution helpers for Strip-Only mov_text/tx3g fallback handling."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from ..core.output_timestamps import build_output_timestamp_args
from ..core.media_stream_selection import primary_ffmpeg_video_index

from .converter_strip_runtime import progress as _progress, subtitle_rules as _subtitle_rules, tools as _tools
from .converter_strip_subtitles import build_strip_subtitle_args, selected_strip_mkv_mov_text_streams
from .subtitle_sidecar_service import SubtitleSidecarService


@dataclass(frozen=True)
class StripMovTextFallbackResult:
    attempted: bool = False
    success: bool = False
    sidecar_paths: tuple[str, ...] = ()
    externalized_stream_indices: tuple[int, ...] = ()


def run_strip_command(
    worker,
    *,
    inp: str,
    out: str,
    container: str,
    audio_input_args,
    audio_args,
    subtitle_args,
    media_info=None,
    on_returncode=None,
) -> bool:
    cmd = [
        _tools(worker).ffmpeg,
        "-y",
        "-loglevel",
        "error",
        *audio_input_args,
        "-i",
        inp,
        *audio_args,
        *subtitle_args,
    ]
    if str(container or "mkv").lower() == "mp4":
        cmd += ["-movflags", "+faststart"]
    index = primary_ffmpeg_video_index(media_info)
    selector = f"0:{index}" if index is not None else "0:v:0"
    cmd += ["-map", selector, "-c:v", "copy", *build_output_timestamp_args(container), out]
    returncode = _progress(worker).run(cmd)
    if on_returncode is not None:
        on_returncode(returncode)
    return returncode == 0


def retry_with_mov_text_backup(
    worker,
    *,
    inp: str,
    out: str,
    mi,
    ov,
    container: str,
    audio_input_args,
    audio_args,
) -> StripMovTextFallbackResult:
    mov_streams = selected_strip_mkv_mov_text_streams(worker, mi, ov, container)
    if not mov_streams:
        return StripMovTextFallbackResult()

    service = SubtitleSidecarService(
        ffmpeg_path=_tools(worker).ffmpeg,
        subtitle_rules=_subtitle_rules(worker),
        log=worker.log,
        worker=worker,
    )
    backup = service.export_mov_text_backup_result(
        input_path=inp,
        output_base=Path(out).with_suffix(""),
        streams=mov_streams,
    )
    if not backup.complete:
        worker.log(f"❌ Strip-Only mov_text-Fallback: {backup.failure_summary()}", "error")
        return StripMovTextFallbackResult(True, False, tuple(backup.exported_paths))

    indices = tuple(int(stream.index) for stream in mov_streams)
    worker.log(
        "⚠️ Strip-Only: mov_text→SRT fehlgeschlagen; Originalspur wurde verlustfrei "
        "als Subtitle-only-MP4 gesichert. Remux wird ohne diese interne Spur wiederholt.",
        "warn",
    )
    subtitle_args = build_strip_subtitle_args(
        worker,
        mi,
        ov,
        container,
        exclude_mkv_stream_indices=set(indices),
    )
    success = run_strip_command(
        worker,
        inp=inp,
        out=out,
        container=container,
        audio_input_args=audio_input_args,
        audio_args=audio_args,
        subtitle_args=subtitle_args,
        media_info=mi,
    )
    paths = tuple(backup.exported_paths)
    if success:
        return StripMovTextFallbackResult(True, True, paths, indices)

    for item in paths:
        try:
            Path(item).unlink(missing_ok=True)
        except OSError:
            pass
    return StripMovTextFallbackResult(True, False)
