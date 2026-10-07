"""Pin input video selection to the analyzed global FFmpeg stream index."""
from __future__ import annotations

import re


def _global_stream_index(value):
    if isinstance(value, bool):
        return None
    text = str(value).strip()
    if not re.fullmatch(r"[0-9]+", text):
        return None
    try:
        return int(text)
    except ValueError:
        return None


def primary_ffmpeg_video_index(media_info) -> int | None:
    """Return the trusted global ffprobe/FFmpeg stream index for the primary video.

    ``VideoStream.index`` is the global FFmpeg stream index.  It must not be
    confused with a per-type selector (``v:0``) or a Matroska TrackNumber.
    Legacy/unit-test media objects without a primary video return ``None`` so
    existing compatibility callers can retain their explicit selectors.
    """
    video = getattr(media_info, "primary_video", None)
    if video is None:
        return None
    return _global_stream_index(getattr(video, "index", None))


def pin_primary_video_selector(vf_args: list, source_stream_index: int | None) -> list:
    """Pin generic input-0 video selectors to one global FFmpeg stream index.

    GUI/planning code historically emits ``0:v:0``.  Once analysis has a
    trusted global index we replace only selectors that still refer to the
    generic first video; named filter outputs such as ``[vout]`` remain intact.
    """
    if source_stream_index is None:
        return list(vf_args)
    index = _global_stream_index(source_stream_index)
    if index is None:
        return list(vf_args)

    selector = f"0:{index}"
    out = list(vf_args)
    for pos, value in enumerate(out):
        text = str(value)
        if pos > 0 and out[pos - 1] == "-map" and text in {"0:v", "0:v:0"}:
            out[pos] = selector
            continue
        if "[0:v:0]" in text or "[0:v]" in text:
            text = text.replace("[0:v:0]", f"[{selector}]")
            text = text.replace("[0:v]", f"[{selector}]")
            out[pos] = text
    return out

