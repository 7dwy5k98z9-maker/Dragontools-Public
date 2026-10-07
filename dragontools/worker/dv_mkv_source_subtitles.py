"""Resolve FFmpeg subtitle indices to mkvmerge IDs for direct source muxing."""
from __future__ import annotations

import json

from ..core.lang_codes import canonical_lang
from ..core.strict_numbers import nonnegative_integer


def _text(value) -> str:
    return str(value or "").strip().casefold()


def _codec_family(value) -> str:
    text = _text(value)
    if not text:
        return ""
    if "pgs" in text or "hdmv" in text:
        return "pgs"
    if "vob" in text or "dvd" in text:
        return "dvd_subtitle"
    if "subrip" in text or "srt" in text or "utf" in text or "s_text/utf8" in text:
        return "subrip"
    if "advanced substation" in text or text == "ass":
        return "ass"
    if "substation alpha" in text or text == "ssa":
        return "ssa"
    if "webvtt" in text or text == "vtt":
        return "webvtt"
    return text


def _flag(mapping: dict, key: str):
    if key not in mapping:
        return None
    value = mapping.get(key)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "yes", "true"}
    return bool(value)


def _ff_meta(stream: dict) -> dict:
    tags = stream.get("tags") if isinstance(stream.get("tags"), dict) else {}
    disposition = stream.get("disposition") if isinstance(stream.get("disposition"), dict) else {}
    return {
        "codec": _codec_family(stream.get("codec_name")),
        "language": canonical_lang(tags.get("language")),
        "title": _text(tags.get("title")),
        "forced": _flag(disposition, "forced"),
        "default": _flag(disposition, "default"),
    }


def _mkv_meta(track: dict) -> dict:
    props = track.get("properties") if isinstance(track.get("properties"), dict) else {}
    return {
        "codec": _codec_family(track.get("codec") or props.get("codec_id")),
        "language": canonical_lang(props.get("language")),
        "title": _text(props.get("track_name")),
        "forced": _flag(props, "forced_track"),
        "default": _flag(props, "default_track"),
    }


def _has_metadata(meta: dict) -> bool:
    return bool(meta["codec"] or meta["language"] or meta["title"] or meta["forced"] is not None or meta["default"] is not None)


def _candidate_score(source: dict, candidate: dict) -> int | None:
    score = 0
    for key, weight in (("codec", 4), ("language", 3), ("title", 3)):
        left, right = source.get(key), candidate.get(key)
        if left and right:
            if left != right:
                return None
            score += weight
    for key, weight in (("forced", 2), ("default", 1)):
        left, right = source.get(key), candidate.get(key)
        if left is not None and right is not None:
            if bool(left) != bool(right):
                return None
            score += weight
    return score


def _selected_streams(streams, required_stream_indices):
    if required_stream_indices is None:
        return streams
    required = {nonnegative_integer(i) for i in required_stream_indices}
    inventory = {nonnegative_integer(s['index']) for s in streams}
    if not required <= inventory:
        raise ValueError('Untertitel-Spurzuordnung: geplante Quellspur fehlt')
    return [s for s in streams if nonnegative_integer(s['index']) in required]

def resolve_subtitle_ids(*, path, ffprobe, mkvmerge, capture, required_stream_indices=None) -> dict[int, int]:
    """Map ffprobe global subtitle indices to mkvmerge track IDs.

    Tool-specific track IDs are never equated.  Metadata is used to build an
    unambiguous correspondence; ambiguous matches fail closed.  The old ordinal
    fallback is retained only for deliberately minimal inventories that contain
    no metadata at all (legacy test/tool compatibility).
    """
    def probe(command):
        result = capture(command)
        allowed_codes = {0, 1} if str(command[0]).casefold().endswith(("mkvmerge", "mkvmerge.exe")) else {0}
        if result is None or result.returncode not in allowed_codes or getattr(result, "aborted", False) or getattr(result, "timed_out", False):
            raise ValueError("Untertitel-Spurzuordnung: Quellenanalyse fehlgeschlagen")
        try:
            return json.loads(result.stdout)
        except (ValueError, TypeError) as exc:
            raise ValueError("Untertitel-Spurzuordnung: ungültige Analyseausgabe") from exc

    try:
        streams = probe([
            ffprobe, "-v", "error", "-select_streams", "s", "-show_entries",
            "stream=index,codec_name:stream_tags=language,title:stream_disposition=default,forced",
            "-of", "json", str(path),
        ])["streams"]
        tracks = [t for t in probe([mkvmerge, "-J", str(path)])["tracks"] if t["type"] == "subtitles"]
        if len(streams) != len(tracks):
            raise ValueError("Untertitel-Spurzuordnung: unterschiedliche Spuranzahl")
        inventory_streams = streams
        streams = _selected_streams(streams, required_stream_indices)
        source_meta = [_ff_meta(s) for s in streams]
        target_meta = [_mkv_meta(t) for t in tracks]
        if not any(_has_metadata(meta) for meta in source_meta + target_meta):
            mapping = {nonnegative_integer(s["index"]): nonnegative_integer(t["id"]) for s, t in zip(inventory_streams, tracks)}
            mapping = {nonnegative_integer(s['index']):mapping[nonnegative_integer(s['index'])] for s in streams}
        else:
            mapping: dict[int, int] = {}
            unused = set(range(len(tracks)))
            for stream, meta in zip(streams, source_meta):
                scored = []
                for idx in unused:
                    score = _candidate_score(meta, target_meta[idx])
                    if score is not None and score > 0:
                        scored.append((score, idx))
                if not scored:
                    raise ValueError(
                        f"Untertitel-Spurzuordnung: kein eindeutiger mkvmerge-Track für ffprobe-Stream {stream.get('index')}"
                    )
                best = max(score for score, _ in scored)
                winners = [idx for score, idx in scored if score == best]
                if len(winners) != 1:
                    raise ValueError(
                        f"Untertitel-Spurzuordnung mehrdeutig für ffprobe-Stream {stream.get('index')}"
                    )
                chosen = winners[0]
                mapping[nonnegative_integer(stream["index"])] = nonnegative_integer(tracks[chosen]["id"])
                unused.remove(chosen)
        if len(mapping) != len(streams) or len(set(mapping.values())) != len(streams):
            raise ValueError("Untertitel-Spurzuordnung: doppelte Spurkennungen")
        return mapping
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("Untertitel-Spurzuordnung: unvollständige Analyseausgabe") from exc


def direct_subtitle_args(track, track_id: int) -> list[str]:
    track_id = nonnegative_integer(track_id)
    language = str(track.language or "und").strip().lower()
    title = str(track.title or "").replace('"', "'").strip()
    args = [
        "--no-video", "--no-audio", "--no-buttons", "--no-attachments",
        "--no-chapters", "--no-global-tags", "--no-track-tags",
        "--subtitle-tracks", str(track_id), "--language", f"{track_id}:{language}",
        "--forced-display-flag", f"{track_id}:{'yes' if track.forced else 'no'}",
        "--default-track-flag", f"{track_id}:{'yes' if bool(getattr(track, 'default', False)) else 'no'}",
    ]
    if title:
        args += ["--track-name", f"{track_id}:{title}"]
    return args + [str(track.path)]
