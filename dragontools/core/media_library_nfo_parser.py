from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


def _int_text(value: str | None) -> int | None:
    try:
        return int(str(value or "").strip())
    except (TypeError, ValueError):
        return None


def _nfo_type_for_root(tag: str) -> str:
    local = (tag or "").rsplit("}", 1)[-1].casefold()
    return {
        "movie": "movie",
        "episodedetails": "episode",
        "tvshow": "series",
        "season": "season",
    }.get(local, local or "unknown")


def _child_text(root: ET.Element, *tags: str) -> str | None:
    wanted = {tag.casefold() for tag in tags}
    for child in root:
        local = child.tag.rsplit("}", 1)[-1].casefold()
        if local in wanted:
            text = (child.text or "").strip()
            if text:
                return text
    return None


def _provider_ids(root: ET.Element) -> dict[str, str]:
    result: dict[str, str] = {}
    ignored_generic_ids = {
        "musicbrainzalbum",
        "musicbrainzartist",
        "audiodbartist",
        "audiodbalbum",
    }
    for child in root.iter():
        local = child.tag.rsplit("}", 1)[-1].casefold()
        text = (child.text or "").strip()
        if not text:
            continue
        if local == "uniqueid":
            provider = str(child.attrib.get("type") or "").strip().casefold()
            if provider:
                result[provider] = text
            continue
        if local in {"tmdbid", "tvdbid", "imdbid"}:
            result[local[:-2]] = text
            continue
        if local.endswith("id") and local not in {"id", "uniqueid"}:
            provider = local[:-2].strip()
            if provider and provider not in ignored_generic_ids:
                result.setdefault(provider, text)
    return result


def parse_nfo(path: str | Path) -> dict[str, Any]:
    root = ET.parse(Path(path)).getroot()
    return {
        "nfo_type": _nfo_type_for_root(root.tag),
        "title": _child_text(root, "title"),
        "original_title": _child_text(root, "originaltitle", "original_title"),
        "series_title": _child_text(root, "showtitle", "seriesname"),
        "season": _int_text(_child_text(root, "season")),
        "episode": _int_text(_child_text(root, "episode")),
        "year": _int_text(_child_text(root, "year")),
        "runtime_minutes": _int_text(_child_text(root, "runtime")),
        "provider_ids": _provider_ids(root),
    }
