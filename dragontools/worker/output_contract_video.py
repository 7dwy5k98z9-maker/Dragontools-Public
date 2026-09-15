# -*- coding: utf-8 -*-
"""Video-part verification for expected media contracts."""
from __future__ import annotations

import re

from ..core.media_metadata import normalize_video_codec
from .media_contract_types import ExpectedMediaContract


def video_bit_depth(stream: dict) -> int | None:
    try:
        value = int(stream.get("bits_per_raw_sample"))
        if value > 0:
            return value
    except (TypeError, ValueError):
        pass
    pix_fmt = str(stream.get("pix_fmt") or "").lower()
    match = re.search(r"(?:p|p0|yuv\d+p)(10|12|14|16)(?:le|be)?$", pix_fmt)
    if match:
        return int(match.group(1))
    if "10" in pix_fmt:
        return 10
    if "12" in pix_fmt:
        return 12
    return 8 if pix_fmt else None


def verify_video_contract(contract: ExpectedMediaContract, streams: list[dict]) -> list[str]:
    messages: list[str] = []
    if len(streams) != contract.video_stream_count:
        messages.append(
            f"Videostream-Anzahl abweichend: erwartet {contract.video_stream_count}, gefunden {len(streams)}."
        )
    if not streams:
        return messages

    video = streams[0]
    actual_codec = normalize_video_codec(video.get("codec_name"))
    expected_codec = normalize_video_codec(contract.video_codec)
    if expected_codec and actual_codec != expected_codec:
        messages.append(
            f"Videocodec abweichend: erwartet {expected_codec}, gefunden {actual_codec or '<unbekannt>'}."
        )
    if contract.min_video_bit_depth is not None:
        depth = video_bit_depth(video)
        if depth is None or depth < contract.min_video_bit_depth:
            messages.append(
                f"Video-Bittiefe abweichend: mindestens {contract.min_video_bit_depth} Bit erwartet, "
                f"gefunden {depth if depth is not None else '<unbekannt>'}."
            )
    try:
        width, height = int(video.get("width") or 0), int(video.get("height") or 0)
    except (TypeError, ValueError):
        width = height = 0
    if contract.expected_width is not None and width != contract.expected_width:
        messages.append(
            f"Video-Breite abweichend: erwartet {contract.expected_width}, gefunden {width or '<unbekannt>'}."
        )
    if contract.expected_height is not None and height != contract.expected_height:
        messages.append(
            f"Video-Hoehe abweichend: erwartet {contract.expected_height}, gefunden {height or '<unbekannt>'}."
        )
    return messages
