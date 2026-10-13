"""Read Matroska's actual WritingApp, independently of copied metadata tags."""
from __future__ import annotations


def _vint(data, offset, *, element_id=False):
    if offset >= len(data) or not data[offset]:
        raise ValueError("Invalid EBML integer")
    width = 9 - data[offset].bit_length()
    end = offset + width
    if end > len(data):
        raise ValueError("Incomplete EBML integer")
    value = int.from_bytes(data[offset:end], "big")
    if not element_id:
        value &= (1 << (7 * width)) - 1
    return value, end


def _elements(data, start, limit):
    position = start
    for _ in range(512):
        if position >= limit:
            return
        element, after_id = _vint(data, position, element_id=True)
        size, content = _vint(data, after_id)
        end = content + size
        yield element, content, end
        position = end


def matroska_writing_application(path) -> str:
    """Read at most 64 KiB. Unavailable/late headers return no author guess."""
    try:
        with open(path, "rb") as source:
            data = source.read(65536)
        if not data.startswith(bytes.fromhex("1a45dfa3")):
            return ""
        segment = next((row for row in _elements(data, 0, len(data)) if row[0] == 0x18538067), None)
        if segment is None:
            return ""
        info = next((row for row in _elements(data, segment[1], min(segment[2], len(data))) if row[0] == 0x1549A966), None)
        if info is None:
            return ""
        app = next((row for row in _elements(data, info[1], min(info[2], len(data))) if row[0] == 0x5741), None)
        return data[app[1]:app[2]].decode("utf-8", errors="replace").strip("\0") if app and app[2] <= len(data) else ""
    except (OSError, ValueError):
        return ""
