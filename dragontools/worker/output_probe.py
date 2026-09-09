from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class OutputProbeData:
    format_name: str
    duration_s: float | None
    streams: tuple[dict, ...]

    @property
    def video_streams(self) -> list[dict]:
        return [stream for stream in self.streams if stream.get("codec_type") == "video"]

    @property
    def audio_streams(self) -> list[dict]:
        return [stream for stream in self.streams if stream.get("codec_type") == "audio"]

    @property
    def subtitle_streams(self) -> list[dict]:
        return [stream for stream in self.streams if stream.get("codec_type") == "subtitle"]

    @property
    def usable(self) -> bool:
        return bool(self.format_name or self.streams)


def probe_output(
    path: Path,
    *,
    ffprobe_path: str,
    run_process: Callable[..., Any],
    no_window_kwargs: dict[str, Any],
) -> OutputProbeData:
    completed = run_process(
        [
            ffprobe_path,
            "-v", "error",
            "-show_entries",
            (
                "format=format_name,duration:"
                "stream=index,codec_type,codec_name,codec_tag_string,profile,width,height,"
                "pix_fmt,bits_per_raw_sample,color_space,color_transfer,color_primaries,"
                "channels,channel_layout:stream_tags=language:"
                "stream_disposition=forced:stream_side_data"
            ),
            "-of", "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=10,
        **no_window_kwargs,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or "ffprobe konnte die Ausgabe nicht lesen.").strip())

    payload = json.loads(completed.stdout or "{}")
    fmt = payload.get("format") or {}
    try:
        duration = float(fmt.get("duration"))
    except (TypeError, ValueError):
        duration = None
    return OutputProbeData(
        format_name=str(fmt.get("format_name") or ""),
        duration_s=duration,
        streams=tuple(payload.get("streams") or ()),
    )
