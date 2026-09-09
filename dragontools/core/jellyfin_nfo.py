# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .online_metadata import EpisodeMetadataSuggestion, MovieMetadataSuggestion
from .process_runner import subprocess_no_window_kwargs


def write_movie_nfo(
    path: str | Path,
    suggestion: MovieMetadataSuggestion,
    *,
    video_path: str | Path | None = None,
    ffprobe_path: str = "",
    include_fileinfo: bool = True,
) -> Path:
    target = Path(path)
    root = ET.Element("movie")
    _add_text(root, "title", suggestion.title)
    _add_text(root, "originaltitle", suggestion.original_title)
    _add_text(root, "sorttitle", suggestion.title)
    _add_text(root, "plot", suggestion.overview)
    _add_text(root, "outline", suggestion.overview)
    _add_text(root, "tagline", suggestion.tagline)
    _add_text(root, "year", suggestion.release_year)
    _add_text(root, "premiered", suggestion.release_date)
    _add_text(root, "releasedate", suggestion.release_date)
    _add_text(root, "runtime", suggestion.runtime_min)
    _add_text(root, "rating", _format_float(suggestion.vote_average))
    _add_text(root, "mpaa", suggestion.certification)
    _add_text(root, "id", suggestion.imdb_id or suggestion.tmdb_id)
    _add_text(root, "tmdbid", suggestion.tmdb_id)
    _add_text(root, "imdbid", suggestion.imdb_id)
    _add_uniqueid(root, "tmdb", suggestion.tmdb_id, default=not bool(suggestion.imdb_id))
    _add_uniqueid(root, "imdb", suggestion.imdb_id, default=bool(suggestion.imdb_id))
    _add_text(root, "trailer", suggestion.trailer_url)
    _add_many(root, "country", suggestion.countries)
    _add_many(root, "genre", suggestion.genres)
    _add_many(root, "studio", suggestion.studios)
    _add_many(root, "tag", suggestion.tags)
    _add_many(root, "director", suggestion.directors)
    _add_many(root, "credits", suggestion.writers)

    if suggestion.has_collection:
        set_el = ET.SubElement(root, "set")
        _add_text(set_el, "name", suggestion.collection_name)
        _add_text(root, "collectionnumber", suggestion.collection_id)

    _add_actors(root, suggestion.actors)
    _append_fileinfo(root, video_path, ffprobe_path, include_fileinfo)
    _write_xml(target, root)
    return target


def write_episode_nfo(
    path: str | Path,
    suggestion: EpisodeMetadataSuggestion,
    *,
    video_path: str | Path | None = None,
    ffprobe_path: str = "",
    include_fileinfo: bool = True,
) -> Path:
    target = Path(path)
    root = ET.Element("episodedetails")
    _add_text(root, "title", suggestion.title)
    _add_text(root, "showtitle", suggestion.show_name)
    _add_text(root, "season", suggestion.season_number)
    _add_text(root, "episode", suggestion.episode_number)
    _add_text(root, "plot", suggestion.overview)
    _add_text(root, "aired", suggestion.air_date)
    _add_text(root, "premiered", suggestion.air_date)
    _add_text(root, "runtime", suggestion.runtime_min)
    _add_text(root, "rating", _format_float(suggestion.vote_average))
    provider = str(getattr(suggestion, "provider", "tmdb") or "tmdb").lower()
    provider_episode_id = getattr(suggestion, "episode_provider_id", None) or suggestion.episode_tmdb_id
    _add_text(root, "id", suggestion.imdb_id or provider_episode_id)
    if provider == "thetvdb":
        _add_text(root, "tvdbid", provider_episode_id)
    else:
        _add_text(root, "tmdbid", suggestion.episode_tmdb_id)
    _add_text(root, "imdbid", suggestion.imdb_id)
    _add_uniqueid(root, "tvdb" if provider == "thetvdb" else "tmdb", provider_episode_id, default=not bool(suggestion.imdb_id))
    _add_uniqueid(root, "imdb", suggestion.imdb_id, default=bool(suggestion.imdb_id))
    _add_many(root, "director", suggestion.directors)
    _add_many(root, "credits", suggestion.writers)
    _add_actors(root, suggestion.actors)
    _append_fileinfo(root, video_path, ffprobe_path, include_fileinfo)
    _write_xml(target, root)
    return target


def build_fileinfo(video_path: str | Path, ffprobe_path: str) -> ET.Element | None:
    if not video_path or not ffprobe_path:
        return None
    path = Path(video_path)
    if not path.exists():
        return None
    try:
        proc = subprocess.run(
            [
                ffprobe_path,
                "-v",
                "error",
                "-show_entries",
                (
                    "format=duration,bit_rate:"
                    "stream=index,codec_type,codec_name,width,height,display_aspect_ratio,"
                    "avg_frame_rate,bit_rate,channels,sample_rate:stream_tags=language,title"
                ),
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            **subprocess_no_window_kwargs(),
            timeout=30,
        )
        if proc.returncode != 0:
            return None
        data = json.loads(proc.stdout or "{}")
    except Exception:
        return None

    streams = data.get("streams") or []
    if not isinstance(streams, list):
        return None
    root = ET.Element("fileinfo")
    streamdetails = ET.SubElement(root, "streamdetails")
    format_data = data.get("format") or {}
    for stream in streams:
        if not isinstance(stream, dict):
            continue
        typ = str(stream.get("codec_type") or "").lower()
        if typ == "video":
            _append_video_stream(streamdetails, stream, format_data)
        elif typ == "audio":
            _append_audio_stream(streamdetails, stream)
        elif typ == "subtitle":
            _append_subtitle_stream(streamdetails, stream)
    return root if list(streamdetails) else None


def _append_video_stream(parent: ET.Element, stream: dict[str, Any], format_data: dict[str, Any]) -> None:
    video = ET.SubElement(parent, "video")
    _add_text(video, "codec", stream.get("codec_name"))
    _add_text(video, "width", stream.get("width"))
    _add_text(video, "height", stream.get("height"))
    _add_text(video, "aspect", stream.get("display_aspect_ratio"))
    _add_text(video, "bitrate", stream.get("bit_rate") or format_data.get("bit_rate"))
    _add_text(video, "durationinseconds", _duration_seconds(format_data.get("duration")))
    _add_text(video, "framerate", _frame_rate(stream.get("avg_frame_rate")))


def _append_audio_stream(parent: ET.Element, stream: dict[str, Any]) -> None:
    audio = ET.SubElement(parent, "audio")
    _add_text(audio, "codec", stream.get("codec_name"))
    _add_text(audio, "language", (stream.get("tags") or {}).get("language"))
    _add_text(audio, "channels", stream.get("channels"))
    _add_text(audio, "bitrate", stream.get("bit_rate"))
    _add_text(audio, "samplingrate", stream.get("sample_rate"))


def _append_subtitle_stream(parent: ET.Element, stream: dict[str, Any]) -> None:
    subtitle = ET.SubElement(parent, "subtitle")
    _add_text(subtitle, "language", (stream.get("tags") or {}).get("language"))
    _add_text(subtitle, "codec", stream.get("codec_name"))


def _append_fileinfo(
    root: ET.Element,
    video_path: str | Path | None,
    ffprobe_path: str,
    include_fileinfo: bool,
) -> None:
    if not include_fileinfo or video_path is None:
        return
    fileinfo = build_fileinfo(video_path, ffprobe_path)
    if fileinfo is not None:
        root.append(fileinfo)


def _add_text(parent: ET.Element, tag: str, value: Any) -> None:
    if value is None:
        return
    text = str(value).strip()
    if text == "":
        return
    ET.SubElement(parent, tag).text = text


def _add_many(parent: ET.Element, tag: str, values: tuple[str, ...] | list[str]) -> None:
    for value in values or ():
        _add_text(parent, tag, value)


def _add_actors(parent: ET.Element, actors: tuple[dict[str, Any], ...]) -> None:
    for actor_data in actors or ():
        actor = ET.SubElement(parent, "actor")
        _add_text(actor, "name", actor_data.get("name"))
        _add_text(actor, "role", actor_data.get("role"))
        _add_text(actor, "sortorder", actor_data.get("sortorder"))


def _add_uniqueid(parent: ET.Element, id_type: str, value: Any, *, default: bool = False) -> None:
    if value is None or str(value).strip() == "":
        return
    unique = ET.SubElement(parent, "uniqueid")
    unique.set("type", id_type)
    if default:
        unique.set("default", "true")
    unique.text = str(value).strip()


def _format_float(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _duration_seconds(value: Any) -> int | None:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _frame_rate(value: Any) -> str:
    text = str(value or "").strip()
    if "/" not in text:
        return text
    num, den = text.split("/", 1)
    try:
        denominator = float(den)
        if denominator == 0:
            return text
        return f"{float(num) / denominator:.3f}".rstrip("0").rstrip(".")
    except ValueError:
        return text


def _write_xml(path: Path, root: ET.Element) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _indent(root)
    body = ET.tostring(root, encoding="unicode", short_empty_elements=False)
    path.write_text(
        '<?xml version="1.0" encoding="utf-8" standalone="yes"?>\n' + body + "\n",
        encoding="utf-8",
    )


def _indent(elem: ET.Element, level: int = 0) -> None:
    indent = "\n" + level * "  "
    child_indent = "\n" + (level + 1) * "  "
    children = list(elem)
    if children:
        if not elem.text or not elem.text.strip():
            elem.text = child_indent
        for child in children:
            _indent(child, level + 1)
        if not elem.tail or not elem.tail.strip():
            elem.tail = indent
    elif level and (not elem.tail or not elem.tail.strip()):
        elem.tail = indent
