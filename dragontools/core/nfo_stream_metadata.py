# -*- coding: utf-8 -*-
"""Safe, targeted stream-language updates for existing Jellyfin/Kodi NFO files."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import xml.etree.ElementTree as StdET

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

from .lang_codes import mkv_language_tags
from .media_library_nfo_parser import MAX_NFO_BYTES


class NfoStreamMetadataError(ValueError):
    pass


def _local_name(tag: str) -> str:
    return str(tag or "").rsplit("}", 1)[-1].casefold()


def resolve_existing_nfo(video_path: str | Path, preferred_path: str | Path | None = None) -> Path | None:
    preferred = str(preferred_path or "").strip()
    candidates: list[Path] = []
    if preferred:
        candidates.append(Path(preferred))
    video = Path(video_path)
    candidates.extend([video.with_suffix(".nfo"), video.parent / "movie.nfo"])
    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(str(candidate))
        if key in seen:
            continue
        seen.add(key)
        if candidate.is_file():
            return candidate
    return None


def _read_bounded(path: Path) -> bytes:
    with path.open("rb") as handle:
        payload = handle.read(MAX_NFO_BYTES + 1)
    if len(payload) > MAX_NFO_BYTES:
        raise NfoStreamMetadataError(
            f"NFO ist zu groß ({len(payload)} Byte gelesen; Limit {MAX_NFO_BYTES} Byte): {path}"
        )
    return payload


def _parse_safe(path: Path) -> StdET.Element:
    try:
        return SafeET.fromstring(
            _read_bounded(path),
            forbid_dtd=True,
            forbid_entities=True,
            forbid_external=True,
        )
    except (StdET.ParseError, DefusedXmlException, OSError, ValueError) as exc:
        raise NfoStreamMetadataError(f"NFO konnte nicht sicher gelesen werden: {path}: {exc}") from exc


def _streamdetails(root: StdET.Element) -> StdET.Element | None:
    for element in root.iter():
        if _local_name(element.tag) == "streamdetails":
            return element
    return None


def stage_stream_language_update(
    source_nfo: str | Path,
    target_nfo: str | Path,
    *,
    stream_type: str,
    ordinal: int,
    language: str,
) -> tuple[bool, str]:
    """Write an updated copy of *source_nfo* to *target_nfo*.

    Returns ``(changed, message)``.  If the NFO contains no ``fileinfo`` /
    ``streamdetails`` section there is no stale stream-language value to repair,
    so no update is required and ``changed`` is false.
    """
    source = Path(source_nfo)
    target = Path(target_nfo)
    kind = str(stream_type or "").strip().casefold()
    node_name = {"audio": "audio", "subtitle": "subtitle"}.get(kind)
    if not node_name or int(ordinal or 0) <= 0:
        raise NfoStreamMetadataError("NFO-Stream konnte nicht eindeutig adressiert werden.")

    root = _parse_safe(source)
    details = _streamdetails(root)
    if details is None:
        return False, "NFO enthält keine Streamdetails; kein NFO-Sprachtag zu synchronisieren."

    streams = [child for child in list(details) if _local_name(child.tag) == node_name]
    index = int(ordinal) - 1
    if index >= len(streams):
        raise NfoStreamMetadataError(
            f"NFO enthält nur {len(streams)} {node_name}-Stream(s); Track {ordinal} kann nicht sicher zugeordnet werden."
        )

    legacy, _ietf = mkv_language_tags(language)
    stream = streams[index]
    language_node = next((child for child in list(stream) if _local_name(child.tag) == "language"), None)
    if language_node is None:
        language_node = StdET.SubElement(stream, "language")
    old_value = str(language_node.text or "").strip().casefold()
    if old_value == legacy.casefold():
        return False, f"NFO-Sprachtag ist bereits {legacy}."
    language_node.text = legacy

    target.parent.mkdir(parents=True, exist_ok=True)
    payload = StdET.tostring(root, encoding="utf-8", xml_declaration=True, short_empty_elements=False)
    with target.open("wb") as handle:
        handle.write(payload)
        handle.write(b"\n")
    return True, f"NFO-Sprachtag auf {legacy} aktualisiert."


__all__ = [
    "NfoStreamMetadataError",
    "resolve_existing_nfo",
    "stage_stream_language_update",
]
