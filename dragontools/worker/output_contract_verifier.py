from __future__ import annotations

import re

from ..core.lang_codes import canonical_lang
from ..core.media_metadata import normalize_video_codec
from .media_contract import _audio_codec_family, _subtitle_codec_family
from .media_contract_types import ExpectedMediaContract
from .workflow_engine import WorkflowVerifyResult


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


def compare_audio_tracks(contract: ExpectedMediaContract, streams: list[dict]) -> list[str]:
    expected = contract.audio_tracks
    if len(streams) != len(expected):
        return [f"Audiospur-Anzahl abweichend: erwartet {len(expected)}, gefunden {len(streams)}."]
    messages: list[str] = []
    for index, (planned, actual) in enumerate(zip(expected, streams), start=1):
        codec = _audio_codec_family(actual.get("codec_name"))
        if planned.codec and codec != planned.codec:
            messages.append(f"Audio #{index}: Codec abweichend: erwartet {planned.codec}, gefunden {codec or '<unbekannt>'}.")
        try:
            channels = int(actual.get("channels") or 0)
        except (TypeError, ValueError):
            channels = 0
        if planned.channels > 0 and channels != planned.channels:
            messages.append(f"Audio #{index}: Kanalzahl abweichend: erwartet {planned.channels}, gefunden {channels}.")
        expected_lang = canonical_lang(planned.language)
        if expected_lang and expected_lang != "und":
            actual_lang = canonical_lang((actual.get("tags") or {}).get("language"))
            if actual_lang != expected_lang:
                messages.append(f"Audio #{index}: Sprache abweichend: erwartet {expected_lang}, gefunden {actual_lang or '<nicht gesetzt>'}.")
    return messages


def compare_subtitle_tracks(contract: ExpectedMediaContract, streams: list[dict]) -> list[str]:
    expected = contract.subtitle_tracks
    if len(streams) != len(expected):
        return [f"Untertitelspur-Anzahl abweichend: erwartet {len(expected)}, gefunden {len(streams)}."]
    messages: list[str] = []
    for index, (planned, actual) in enumerate(zip(expected, streams), start=1):
        codec = _subtitle_codec_family(actual.get("codec_name"))
        if planned.codec and codec != planned.codec:
            messages.append(f"Untertitel #{index}: Codec abweichend: erwartet {planned.codec}, gefunden {codec or '<unbekannt>'}.")
        expected_lang = canonical_lang(planned.language)
        if expected_lang and expected_lang != "und":
            actual_lang = canonical_lang((actual.get("tags") or {}).get("language"))
            if actual_lang != expected_lang:
                messages.append(f"Untertitel #{index}: Sprache abweichend: erwartet {expected_lang}, gefunden {actual_lang or '<nicht gesetzt>'}.")
        actual_forced = bool((actual.get("disposition") or {}).get("forced", 0))
        if actual_forced != bool(planned.forced):
            messages.append(f"Untertitel #{index}: Forced-Flag abweichend: erwartet {bool(planned.forced)}, gefunden {actual_forced}.")
    return messages


def apply_contract(
    result: WorkflowVerifyResult,
    contract: ExpectedMediaContract,
    *,
    video_streams: list[dict],
    audio_streams: list[dict],
    subtitle_streams: list[dict],
) -> None:
    messages: list[str] = []
    if len(video_streams) != contract.video_stream_count:
        messages.append(f"Videostream-Anzahl abweichend: erwartet {contract.video_stream_count}, gefunden {len(video_streams)}.")
    if video_streams:
        video = video_streams[0]
        actual_codec = normalize_video_codec(video.get("codec_name"))
        expected_codec = normalize_video_codec(contract.video_codec)
        if expected_codec and actual_codec != expected_codec:
            messages.append(f"Videocodec abweichend: erwartet {expected_codec}, gefunden {actual_codec or '<unbekannt>'}.")
        if contract.min_video_bit_depth is not None:
            depth = video_bit_depth(video)
            if depth is None or depth < contract.min_video_bit_depth:
                messages.append(f"Video-Bittiefe abweichend: mindestens {contract.min_video_bit_depth} Bit erwartet, gefunden {depth if depth is not None else '<unbekannt>'}.")
        try:
            width, height = int(video.get("width") or 0), int(video.get("height") or 0)
        except (TypeError, ValueError):
            width = height = 0
        if contract.expected_width is not None and width != contract.expected_width:
            messages.append(f"Video-Breite abweichend: erwartet {contract.expected_width}, gefunden {width or '<unbekannt>'}.")
        if contract.expected_height is not None and height != contract.expected_height:
            messages.append(f"Video-Hoehe abweichend: erwartet {contract.expected_height}, gefunden {height or '<unbekannt>'}.")

    audio_messages = compare_audio_tracks(contract, audio_streams)
    if audio_messages:
        result.audio_ok = False
        messages.extend(audio_messages)
    subtitle_messages = compare_subtitle_tracks(contract, subtitle_streams)
    if subtitle_messages:
        result.subtitle_ok = False
        messages.extend(subtitle_messages)

    metadata_messages: list[str] = []
    if contract.require_hdr and not result.has_hdr:
        metadata_messages.append("HDR-Vertrag verletzt: HDR ist im finalen Videostream nicht nachweisbar.")
    if contract.require_dolby_vision and not result.has_dolby_vision:
        metadata_messages.append("Dolby-Vision-Vertrag verletzt: Dolby Vision ist im finalen Videostream nicht nachweisbar.")
    if contract.require_hdr10plus and not result.has_hdr10plus:
        metadata_messages.append("HDR10+-Vertrag verletzt: HDR10+ ist im finalen Videostream nicht nachweisbar.")
    if metadata_messages:
        result.metadata_ok = False
        messages.extend(metadata_messages)
    result.contract_ok = not messages
    result.messages.extend(messages)
