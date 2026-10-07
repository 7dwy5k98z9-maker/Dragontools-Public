"""Map FFprobe subtitle indices to independently identified Matroska IDs."""

import json
from .output_safety import valid_stream_indices


def parse_matroska_tracks(text):
    tracks = json.loads(text).get("tracks")
    if not isinstance(tracks, list):
        raise ValueError("MKVToolNix lieferte kein tracks-Array.")
    ids = [row.get("id") if isinstance(row, dict) else None for row in tracks]
    if any(type(value) is not int or value < 0 for value in ids) or len(ids) != len(
        set(ids)
    ):
        raise ValueError("Ungültige oder doppelte MKVToolNix-IDs.")
    return tracks


def resolve_subtitle_track_id(probe_text, identify_text, stream_index):
    indices = valid_stream_indices(json.loads(probe_text).get("streams"))
    tracks = [
        row
        for row in parse_matroska_tracks(identify_text)
        if row.get("type") == "subtitles"
    ]
    if len(indices) != len(tracks) or type(stream_index) is not int:
        raise ValueError(
            "FFprobe- und Matroska-Untertitelinventar stimmen nicht überein."
        )
    return tracks[indices.index(stream_index)]["id"]


def injection_track_options(tracks, source_streams):
    """Preserve flags by type/ordinal only after validating inventory sizes."""
    args = []
    for kind, mkv_kind in [
        ("video", "video"),
        ("audio", "audio"),
        ("subtitle", "subtitles"),
    ]:
        source = [row for row in source_streams if row["codec_type"] == kind]
        actual = [row for row in tracks if row.get("type") == mkv_kind]
        if len(source) != len(actual):
            raise ValueError("MKVToolNix- und FFprobe-Inventar stimmen nicht überein.")
        for row, track in zip(source, actual):
            flags = row.get("disposition") or {}
            for key, option in [
                ("default", "--default-track-flag"),
                ("forced", "--forced-display-flag"),
            ]:
                args += [option, f"{track['id']}:{'yes' if flags.get(key) else 'no'}"]
            title = (row.get("tags") or {}).get("title")
            if title:
                args += ["--track-name", f"{track['id']}:{title}"]
    return args
