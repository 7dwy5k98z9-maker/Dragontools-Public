from __future__ import annotations

import logging
import re
from typing import Any, Iterable

from .media_metadata import normalize_video_codec

_log = logging.getLogger(__name__)

_DV_CODEC_TAG_RE = re.compile(
    r"\b(?P<tag>dvhe|dvh1|dva1|dvav|dav1)\."
    r"(?P<profile>\d{1,2})(?:\.(?P<level>\d{1,2}))?\b",
    re.IGNORECASE,
)
_DV_PROFILE_RE = re.compile(r"\bprofile\s*(?:=|:)?\s*(?P<profile>\d{1,2})(?:\.\d+)?\b", re.IGNORECASE)
_HDR10PLUS_RE = re.compile(
    r"(?:\bhdr10\s*\+|\bhdr10plus\b|"
    r"\bsmpte\s*st\s*2094\s*(?:-\s*40|app(?:lication)?\s*4)\b|"
    r"\bst\s*2094\s*(?:-\s*40|app(?:lication)?\s*4)\b|"
    r"\bsmpte2094\s*-?\s*40\b|\bst2094\s*-?\s*40\b)",
    re.IGNORECASE,
)
_DV_TEXT_MARKERS = ("dolby vision", "dovi", "dvhe", "dvh1", "dva1", "dvav", "dav1")


def _default_dv_info() -> dict[str, Any]:
    return {
        "dolby_vision": False,
        "dv_profile": None,
        "dv_profile_major": None,
        "dv_codec_tag": None,
        "dv_level": None,
        "dv_format_raw": None,
        "hdr_format_profile_raw": None,
    }


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return " | ".join(_text(item) for item in value if item is not None)
    if isinstance(value, dict):
        return " | ".join(f"{key}={_text(item)}" for key, item in value.items())
    return str(value)


def _join_values(values: Iterable[Any]) -> str:
    return " | ".join(part for part in (_text(value).strip() for value in values) if part)


def _major_profile(value: Any) -> int | None:
    if value in (None, "", "Ja"):
        return None
    try:
        return int(str(value).strip().split(".", 1)[0])
    except (TypeError, ValueError):
        return None


def contains_hdr10plus_marker(value: Any) -> bool:
    """Return True for the common HDR10+/ST-2094-40 spellings.

    MediaInfo does not always write the literal text ``HDR10+``. In current
    releases a valid HDR10+ stream may be reported only as
    ``SMPTE ST 2094 App 4``.  FFmpeg/ffprobe usually calls the same metadata
    ``HDR Dynamic Metadata SMPTE2094-40 (HDR10+)``.
    """
    return bool(_HDR10PLUS_RE.search(_text(value)))


def _extract_dv_tag(text: str) -> tuple[str | None, int | None, str | None]:
    match = _DV_CODEC_TAG_RE.search(text or "")
    if not match:
        return None, None, None
    tag = match.group("tag").lower()
    profile_text = match.group("profile")
    level_text = match.group("level")
    codec_tag = f"{tag}.{int(profile_text):02d}"
    if level_text is not None:
        codec_tag += f".{int(level_text):02d}"
    return codec_tag, int(profile_text), str(int(level_text)) if level_text is not None else None


def _extract_profile_from_text(text: str) -> int | None:
    match = _DV_PROFILE_RE.search(text or "")
    return int(match.group("profile")) if match else None


def parse_dolby_vision_profile(video_track: dict) -> dict[str, Any]:
    """Parse Dolby-Vision details from a MediaInfo video track.

    Supports both textual MediaInfo variants (``Profile 8.1``) and codec-tag
    variants such as ``dvhe.08.06`` / ``dvh1.08.06``. AVC-era tags
    (``dva1``/``dvav``) and ``dav1`` are accepted for detection as well so the
    analyzer does not silently discard a valid but unsupported DV source.
    """
    result = _default_dv_info()

    hdr_format = _text(video_track.get("HDR_Format") or video_track.get("HDR format"))
    hdr_format_profile = _text(
        video_track.get("HDR_Format_Profile")
        or video_track.get("HDR Format profile")
        or video_track.get("HDR_format_profile")
    )
    hdr_format_level = _text(
        video_track.get("HDR_Format_Level")
        or video_track.get("HDR Format level")
        or video_track.get("HDR_format_level")
    )

    fields = _join_values(
        (
            hdr_format,
            hdr_format_profile,
            hdr_format_level,
            video_track.get("HDR_Format_Settings"),
            video_track.get("HDR Format settings"),
            video_track.get("HDR_Format_Commercial"),
            video_track.get("HDR_Format_String"),
            video_track.get("HDR_Format_Compatibility"),
            video_track.get("Format_Profile"),
            video_track.get("CodecID"),
            video_track.get("CodecID/String"),
            video_track.get("CodecID_Compatible"),
        )
    )
    fields_low = fields.lower()
    codec_tag, tag_profile, tag_level = _extract_dv_tag(fields)
    is_dv = codec_tag is not None or any(marker in fields_low for marker in _DV_TEXT_MARKERS)
    if not is_dv:
        return result

    result["dolby_vision"] = True
    result["dv_format_raw"] = hdr_format or None
    result["hdr_format_profile_raw"] = hdr_format_profile or None
    result["dv_codec_tag"] = codec_tag
    result["dv_level"] = hdr_format_level or tag_level

    profile = tag_profile or _extract_profile_from_text(fields)
    if profile is not None:
        result["dv_profile"] = str(profile)
        result["dv_profile_major"] = profile
    return result


def parse_dolby_vision_from_ffprobe_stream(stream: dict) -> dict[str, Any]:
    """Parse Dolby-Vision information from an ffprobe video stream.

    Modern ffprobe versions expose a ``DOVI configuration record`` with
    ``dv_profile`` and ``dv_level``.  Older/container-specific builds may only
    expose a DV codec tag, so both forms are handled.
    """
    result = _default_dv_info()
    stream_text = _join_values(
        (
            stream.get("codec_tag_string"),
            stream.get("codec_tag"),
            stream.get("profile"),
            stream.get("codec_long_name"),
            stream.get("tags"),
        )
    )
    codec_tag, tag_profile, tag_level = _extract_dv_tag(stream_text)
    if codec_tag:
        result["dolby_vision"] = True
        result["dv_codec_tag"] = codec_tag
        result["dv_profile_major"] = tag_profile
        result["dv_profile"] = str(tag_profile) if tag_profile is not None else None
        result["dv_level"] = tag_level
    elif any(marker in stream_text.lower() for marker in _DV_TEXT_MARKERS):
        result["dolby_vision"] = True

    for side_data in stream.get("side_data_list") or []:
        sd_type = _text(side_data.get("side_data_type")).lower()
        if not ("dovi" in sd_type or "dolby vision" in sd_type):
            continue
        result["dolby_vision"] = True
        profile = _major_profile(side_data.get("dv_profile"))
        if profile is None:
            profile = _major_profile(side_data.get("profile"))
        if profile is not None:
            result["dv_profile_major"] = profile
            result["dv_profile"] = str(profile)
        level = side_data.get("dv_level")
        if level not in (None, ""):
            result["dv_level"] = str(level)

    return result


def merge_dolby_vision_info(
    mediainfo_info: dict[str, Any],
    ffprobe_info: dict[str, Any],
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Merge MediaInfo and ffprobe DV evidence without losing conflicts.

    Structured ffprobe ``DOVI configuration record`` values win only for the
    numeric profile/level when they are present; MediaInfo remains the source
    for its richer raw strings and codec tag. A disagreement is surfaced as an
    analysis warning instead of being silently ignored.
    """
    result = _default_dv_info()
    mi_detected = bool(mediainfo_info.get("dolby_vision"))
    fp_detected = bool(ffprobe_info.get("dolby_vision"))
    result["dolby_vision"] = mi_detected or fp_detected
    if not result["dolby_vision"]:
        return result

    mi_profile = _major_profile(mediainfo_info.get("dv_profile_major") or mediainfo_info.get("dv_profile"))
    fp_profile = _major_profile(ffprobe_info.get("dv_profile_major") or ffprobe_info.get("dv_profile"))
    if mi_profile is not None and fp_profile is not None and mi_profile != fp_profile and warnings is not None:
        warnings.append(
            "[DV-Erkennung] MediaInfo und ffprobe melden unterschiedliche Dolby-Vision-Profile "
            f"(MediaInfo={mi_profile}, ffprobe={fp_profile}); verwende ffprobe-DOVI-Profil {fp_profile}."
        )

    profile = fp_profile if fp_profile is not None else mi_profile
    if profile is not None:
        result["dv_profile_major"] = profile
        result["dv_profile"] = str(profile)

    result["dv_codec_tag"] = mediainfo_info.get("dv_codec_tag") or ffprobe_info.get("dv_codec_tag")
    result["dv_level"] = ffprobe_info.get("dv_level") or mediainfo_info.get("dv_level")
    result["dv_format_raw"] = mediainfo_info.get("dv_format_raw")
    result["hdr_format_profile_raw"] = mediainfo_info.get("hdr_format_profile_raw")
    return result


def choose_dovi_convert_mode(mi: object) -> str:
    """Choose the dovi_tool -m mode from the detected Dolby-Vision profile."""
    raw_profile = getattr(mi, "dv_profile_major", None)
    if raw_profile in (None, ""):
        raw_profile = getattr(mi, "dv_profile", None)
    profile = _major_profile(raw_profile)

    if profile == 5:
        _log.info("DV-Profil erkannt: 5 -> dovi_tool Mode 3 (Profile 5 -> 8.1)")
        return "3"
    if profile == 7:
        _log.info("DV-Profil erkannt: 7 -> dovi_tool Mode 2 (Profile 8.1 compatible)")
        return "2"
    if profile == 8:
        _log.info("DV-Profil erkannt: 8 -> dovi_tool Mode 2 / Normalisierung")
        return "2"

    _log.warning(
        "DV-Profil unbekannt (dv_profile_major=%s) -> dovi_tool Mode 2 als sicherer Default.",
        profile,
    )
    return "2"


def detect_hdr_from_mediainfo_track(video_track: dict) -> tuple[bool, bool, str | None]:
    """Detect HDR, HDR10+ and Dolby Vision from structured MediaInfo fields."""
    dv_info = parse_dolby_vision_profile(video_track)
    dv_profile_compat: str | None = None
    if dv_info["dolby_vision"]:
        dv_profile_compat = dv_info["dv_profile"] or "Ja"

    hdr_fields = _join_values(
        (
            video_track.get("HDR_Format"),
            video_track.get("HDR format"),
            video_track.get("HDR_Format_String"),
            video_track.get("HDR_Format_Compatibility"),
            video_track.get("HDR_Format_Commercial"),
            video_track.get("HDR_Format_Profile"),
            video_track.get("HDR_Format_Settings"),
            video_track.get("Format_AdditionalFeatures"),
        )
    )
    transfer = _text(
        video_track.get("transfer_characteristics")
        or video_track.get("transfer_characteristics_Original")
        or video_track.get("TransferCharacteristics")
    ).lower()
    primaries = _text(
        video_track.get("colour_primaries")
        or video_track.get("colour_primaries_Original")
        or video_track.get("ColorPrimaries")
    ).lower()

    has_hdr10plus = contains_hdr10plus_marker(hdr_fields)
    hdr_fields_low = hdr_fields.lower()
    is_hdr_base = (
        dv_profile_compat is not None
        or has_hdr10plus
        or "hdr10" in hdr_fields_low
        or transfer in {"smpte2084", "pq", "arib-std-b67", "hlg"}
        or "smpte2084" in transfer
        or "st 2084" in transfer
        or "bt2020" in primaries
        or "bt.2020" in primaries
    )
    return is_hdr_base, has_hdr10plus, dv_profile_compat


def detect_hdr_from_ffprobe_stream(stream: dict) -> tuple[bool, bool, str | None]:
    """Detect HDR, HDR10+ and Dolby Vision from structured ffprobe fields."""
    transfer = _text(stream.get("color_transfer")).lower()
    primaries = _text(stream.get("color_primaries")).lower()
    dv_info = parse_dolby_vision_from_ffprobe_stream(stream)
    dv_profile = dv_info["dv_profile"] if dv_info["dv_profile"] is not None else ("Ja" if dv_info["dolby_vision"] else None)

    has_hdr10plus = any(
        contains_hdr10plus_marker(side_data.get("side_data_type"))
        or contains_hdr10plus_marker(side_data)
        for side_data in (stream.get("side_data_list") or [])
    )
    is_hdr = (
        dv_profile is not None
        or has_hdr10plus
        or transfer in {"smpte2084", "arib-std-b67"}
        or "smpte2084" in transfer
        or primaries in {"bt2020", "bt.2020"}
    )
    return is_hdr, has_hdr10plus, dv_profile


def detect_hdr10plus_from_ffprobe_frames(payload: dict) -> bool:
    """Detect frame-level ST-2094-40 metadata from a short ffprobe probe."""
    for frame in payload.get("frames") or []:
        for side_data in frame.get("side_data_list") or []:
            if contains_hdr10plus_marker(side_data.get("side_data_type")) or contains_hdr10plus_marker(side_data):
                return True
    return False


def validate_hdr_flags(
    codec: str,
    bit_depth: int | None,
    pix_fmt: str | None,
    is_hdr: bool,
    has_hdr10plus: bool,
    dv_profile: str | None,
    warnings: list[str],
) -> tuple[bool, bool, str | None]:
    """Apply guards without deleting explicit Dolby-Vision evidence.

    Pipeline support is decided later. Detection must still report DV on AVC
    sources (for example older DV profiles) instead of pretending the metadata
    does not exist.
    """
    codec_norm = normalize_video_codec(codec)

    if bit_depth is not None and bit_depth < 10:
        cleared: list[str] = []
        if has_hdr10plus:
            has_hdr10plus = False
            cleared.append("HDR10+")
        if is_hdr and dv_profile is None:
            is_hdr = False
            cleared.append("HDR")
        if cleared:
            warnings.append(
                f"[HDR-Validierung] bit_depth={bit_depth} < 10 "
                f"(codec={codec_norm}, pix_fmt={pix_fmt}) -> "
                f"{', '.join(cleared)} verworfen; explizites Dolby Vision bleibt als Quellenmetadatum erhalten."
            )

    if codec_norm == "h264" and has_hdr10plus:
        has_hdr10plus = False
        warnings.append(
            "[HDR-Validierung] codec=H.264 -> HDR10+ verworfen; "
            "Dolby Vision wird dagegen weiterhin erkannt und erst von der Pipeline-Capability bewertet."
        )

    if dv_profile is not None:
        is_hdr = True

    return is_hdr, has_hdr10plus, dv_profile
