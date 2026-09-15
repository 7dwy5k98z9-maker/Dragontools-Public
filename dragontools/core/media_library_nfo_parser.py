from __future__ import annotations

import xml.etree.ElementTree as StdET
from pathlib import Path
from typing import Any

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

# NFO files are metadata and should be small. A hard upper bound prevents a
# malformed or hostile file from making the light scan consume unbounded RAM.
MAX_NFO_BYTES = 8 * 1024 * 1024


class NfoParseError(ValueError):
    """Raised when an NFO cannot be parsed safely."""


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


def _child_text(root: StdET.Element, *tags: str) -> str | None:
    wanted = {tag.casefold() for tag in tags}
    for child in root:
        local = child.tag.rsplit("}", 1)[-1].casefold()
        if local in wanted:
            text = (child.text or "").strip()
            if text:
                return text
    return None


def _provider_ids(root: StdET.Element) -> dict[str, str]:
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


def _read_bounded_nfo(path: Path) -> bytes:
    """Read at most MAX_NFO_BYTES + 1 so the memory bound is race-safe."""
    with path.open("rb") as handle:
        payload = handle.read(MAX_NFO_BYTES + 1)
    if len(payload) > MAX_NFO_BYTES:
        raise NfoParseError(
            f"NFO ist zu groß ({len(payload)} Byte gelesen; Limit {MAX_NFO_BYTES} Byte): {path}"
        )
    return payload


def parse_nfo(path: str | Path) -> dict[str, Any]:
    nfo_path = Path(path)
    payload = _read_bounded_nfo(nfo_path)
    try:
        root = SafeET.fromstring(
            payload,
            forbid_dtd=True,
            forbid_entities=True,
            forbid_external=True,
        )
    except (StdET.ParseError, DefusedXmlException, ValueError) as exc:
        raise NfoParseError(f"NFO-XML konnte nicht sicher geparst werden: {nfo_path}: {exc}") from exc

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


__all__ = ["MAX_NFO_BYTES", "NfoParseError", "parse_nfo"]
