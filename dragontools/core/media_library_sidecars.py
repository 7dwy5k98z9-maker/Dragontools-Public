from __future__ import annotations

from pathlib import Path
from typing import Any

_SUBTITLE_SIDECAR_CODECS = {
    ".srt": "subrip", ".ass": "ass", ".ssa": "ssa", ".vtt": "webvtt",
    ".sub": "dvd_subtitle", ".idx": "dvd_subtitle", ".sup": "hdmv_pgs_subtitle",
}
_LANG_HINTS = {
    "de": "deu", "deu": "deu", "ger": "deu", "german": "deu", "deutsch": "deu",
    "en": "eng", "eng": "eng", "english": "eng",
}


def _nfo_status_for_path(path: str | Path) -> str:
    video = Path(path)
    candidates = [video.with_suffix(".nfo"), video.parent / "movie.nfo"]
    return "present" if any(candidate.exists() for candidate in candidates) else "missing"


def _trickplay_status_for_path(path: str | Path) -> str:
    video = Path(path)
    root = video.with_name(f"{video.stem}.trickplay")
    if not root.is_dir():
        return "missing"
    try:
        return "present" if any(root.rglob("*.jpg")) else "empty"
    except OSError:
        return "unknown"


def _language_from_sidecar_name(video: Path, sidecar: Path) -> str | None:
    suffix = sidecar.stem[len(video.stem):].strip(" ._-")
    if not suffix:
        return None
    for token in suffix.replace("-", ".").replace("_", ".").split("."):
        normalized = _LANG_HINTS.get(token.casefold())
        if normalized:
            return normalized
    return None


def _subtitle_sidecar_streams(path: str | Path, start_index: int = 1000) -> list[dict[str, Any]]:
    video = Path(path)
    try:
        entries = list(video.parent.iterdir())
    except OSError:
        return []
    prefix = video.stem.casefold()
    streams: list[dict[str, Any]] = []
    for sidecar in sorted(entries, key=lambda entry: entry.name.casefold()):
        ext = sidecar.suffix.casefold()
        if ext not in _SUBTITLE_SIDECAR_CODECS:
            continue
        if sidecar.stem.casefold() != prefix and not sidecar.stem.casefold().startswith(prefix + "."):
            continue
        streams.append(
            {
                "stream_type": "Subtitle",
                "stream_index": start_index + len(streams),
                "codec": _SUBTITLE_SIDECAR_CODECS[ext],
                "language": _language_from_sidecar_name(video, sidecar),
                "forced": 1 if "forced" in sidecar.stem.casefold() else 0,
                "channels": None,
                "channel_layout": None,
                "bitrate": None,
                "width": None,
                "height": None,
                "hdr_format": None,
                "dv_profile": None,
                "pix_fmt": None,
                "bit_depth": None,
                "profile": None,
                "duration_s": None,
                "frame_count": None,
                "frame_rate": None,
                "frame_rate_mode": None,
                "color_space": None,
                "color_transfer": None,
                "color_primaries": None,
                "source_kind": "external",
                "external_path": str(sidecar),
                "title": sidecar.name,
            }
        )
    return streams
