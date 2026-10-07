"""Verify the requested in-place track property from an actual MKV inventory."""

from ..core.lang_codes import canonical_lang
from .matroska_tracks import parse_matroska_tracks
from .output_safety import stopped


def verify_tag_edit(path, track_index, set_expression, *, mkvmerge, run):
    result = run([mkvmerge, "-J", path], allow_error=True, timeout=60)
    if result.returncode != 0 or stopped(result):
        return False
    tracks = parse_matroska_tracks(result.stdout)
    if track_index >= len(tracks):
        return False
    properties = tracks[track_index].get("properties") or {}
    key, value = set_expression.split("=", 1)
    if key == "language":
        return canonical_lang(properties.get("language")) == canonical_lang(value)
    if key == "flag-forced":
        return properties.get("forced_track") is (value == "1")
    return False
