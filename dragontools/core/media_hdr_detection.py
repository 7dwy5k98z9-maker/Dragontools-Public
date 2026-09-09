from __future__ import annotations

import logging
import re
from typing import Any

from .media_metadata import normalize_video_codec

_log = logging.getLogger(__name__)


def parse_dolby_vision_profile(video_track: dict) -> dict:
    """Parse Dolby-Vision profile details from a MediaInfo video track."""
    result: dict[str, Any] = {
        "dolby_vision": False,
        "dv_profile": None,
        "dv_profile_major": None,
        "dv_codec_tag": None,
        "dv_level": None,
        "dv_format_raw": None,
        "hdr_format_profile_raw": None,
    }

    hdr_format = video_track.get("HDR_Format") or video_track.get("HDR format") or ""
    hdr_format_profile = (
        video_track.get("HDR_Format_Profile")
        or video_track.get("HDR Format profile")
        or video_track.get("HDR_format_profile")
        or ""
    )
    hdr_format_level = (
        video_track.get("HDR_Format_Level")
        or video_track.get("HDR Format level")
        or video_track.get("HDR_format_level")
        or ""
    )
    hdr_format_settings = (
        video_track.get("HDR_Format_Settings")
        or video_track.get("HDR Format settings")
        or ""
    )
    hdr_format_commercial = video_track.get("HDR_Format_Commercial") or ""
    format_profile = video_track.get("Format_Profile") or ""
    codec_id = video_track.get("CodecID") or ""

    dv_fields_low = " | ".join(
        [
            hdr_format,
            hdr_format_profile,
            hdr_format_level,
            hdr_format_settings,
            hdr_format_commercial,
            format_profile,
            codec_id,
        ]
    ).lower()

    is_dv = any(t in dv_fields_low for t in ("dolby vision", "dvhe", "dvh1", "dovi"))
    if not is_dv:
        return result

    result["dolby_vision"] = True
    result["dv_format_raw"] = hdr_format or None
    result["hdr_format_profile_raw"] = hdr_format_profile or None
    result["dv_level"] = hdr_format_level or None

    if hdr_format_profile:
        m = re.search(
            r"(dvh[1e])\.(\d{2})(?:\.(\d{2}))?",
            hdr_format_profile,
            re.IGNORECASE,
        )
        if m:
            codec_prefix = m.group(1).lower()
            major_str = m.group(2)
            minor_str = m.group(3)
            major_num = int(major_str)
            result["dv_profile"] = str(major_num)
            result["dv_profile_major"] = major_num
            result["dv_codec_tag"] = (
                f"{codec_prefix}.{major_str}.{minor_str}"
                if minor_str
                else f"{codec_prefix}.{major_str}"
            )
            return result

    if hdr_format:
        m_tag = re.search(r"(dvh[1e])\.(\d{2})\.(\d{2})", hdr_format, re.IGNORECASE)
        if m_tag:
            codec_prefix = m_tag.group(1).lower()
            major_str = m_tag.group(2)
            minor_str = m_tag.group(3)
            major_num = int(major_str)
            result["dv_profile"] = str(major_num)
            result["dv_profile_major"] = major_num
            result["dv_codec_tag"] = f"{codec_prefix}.{major_str}.{minor_str}"
            return result

        m_prof = re.search(r"profile\s+(\d+)", hdr_format, re.IGNORECASE)
        if m_prof:
            major_num = int(m_prof.group(1))
            result["dv_profile"] = str(major_num)
            result["dv_profile_major"] = major_num
            m_tag2 = re.search(r"(dvh[1e])\.(\d{2})", hdr_format, re.IGNORECASE)
            if m_tag2:
                result["dv_codec_tag"] = f"{m_tag2.group(1).lower()}.{m_tag2.group(2)}"
            return result

    m_tag = re.search(r"(dvh[1e])\.(\d{2})(?:\.(\d{2}))?", dv_fields_low)
    if m_tag:
        codec_prefix = m_tag.group(1)
        major_str = m_tag.group(2)
        minor_str = m_tag.group(3)
        major_num = int(major_str)
        result["dv_profile"] = str(major_num)
        result["dv_profile_major"] = major_num
        result["dv_codec_tag"] = (
            f"{codec_prefix}.{major_str}.{minor_str}"
            if minor_str
            else f"{codec_prefix}.{major_str}"
        )
        return result

    m_prof = re.search(r"profile\s+(\d+)", dv_fields_low)
    if m_prof:
        major_num = int(m_prof.group(1))
        result["dv_profile"] = str(major_num)
        result["dv_profile_major"] = major_num
        return result

    return result


def choose_dovi_convert_mode(mi: object) -> str:
    """Choose the dovi_tool -m mode from the detected Dolby-Vision profile.

    ``dv_profile_major`` stammt im Normalfall als ``int`` aus der Analyse.
    Ältere Cache-/Override-Daten können jedoch Strings enthalten. Gerade P5
    muss auch dann sicher Mode 3 erhalten.
    """
    raw_profile = getattr(mi, "dv_profile_major", None)
    if raw_profile in (None, ""):
        raw_profile = getattr(mi, "dv_profile", None)
    try:
        profile = int(str(raw_profile).strip().split(".", 1)[0])
    except (TypeError, ValueError):
        profile = None

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
        "DV-Profil unbekannt (dv_profile_major=%s) -> "
        "dovi_tool Mode 2 als sicherer Default.",
        profile,
    )
    return "2"


def detect_hdr_from_mediainfo_track(video_track: dict) -> tuple[bool, bool, str | None]:
    """Detect HDR, HDR10+ and Dolby Vision from structured MediaInfo fields."""
    dv_info = parse_dolby_vision_profile(video_track)

    dv_profile_compat: str | None = None
    if dv_info["dolby_vision"]:
        dv_profile_compat = (
            dv_info["dv_profile"] if dv_info["dv_profile"] is not None else "Ja"
        )

    hdr_format_str = (video_track.get("HDR_Format_String") or "").lower()
    hdr_compat = (video_track.get("HDR_Format_Compatibility") or "").lower()
    hdr_commercial = (video_track.get("HDR_Format_Commercial") or "").lower()
    hdr_fields = (
        (dv_info.get("dv_format_raw") or "").lower()
        + " | "
        + hdr_format_str
        + " | "
        + hdr_compat
        + " | "
        + hdr_commercial
    )

    transfer = (
        video_track.get("transfer_characteristics")
        or video_track.get("transfer_characteristics_Original")
        or video_track.get("TransferCharacteristics")
        or ""
    ).lower()
    primaries = (
        video_track.get("colour_primaries")
        or video_track.get("colour_primaries_Source")
        or video_track.get("ColorPrimaries")
        or ""
    ).lower()

    has_hdr10plus = (
        "hdr10+" in hdr_fields
        or "smpte st 2094-40" in hdr_fields
        or "dynamic metadata" in hdr_fields
    )

    is_hdr_base = (
        dv_profile_compat is not None
        or has_hdr10plus
        or "hdr10" in hdr_fields
        or transfer in {"smpte2084", "pq", "arib-std-b67", "hlg"}
        or "smpte2084" in transfer
        or "bt2020" in primaries
        or "bt.2020" in primaries
    )

    return is_hdr_base, has_hdr10plus, dv_profile_compat


def detect_hdr_from_ffprobe_stream(stream: dict) -> tuple[bool, bool, str | None]:
    """Detect HDR, HDR10+ and Dolby Vision from structured ffprobe fields."""
    profile = (stream.get("profile") or "").lower()
    transfer = (stream.get("color_transfer") or "").lower()
    primaries = (stream.get("color_primaries") or "").lower()

    dv_profile: str | None = None
    has_hdr10plus = False

    for sd in stream.get("side_data_list") or []:
        sd_type = (sd.get("side_data_type") or "").lower()
        if "dolby vision" in sd_type or "dovi" in sd_type:
            raw_p = sd.get("dv_profile")
            dv_profile = str(raw_p) if raw_p is not None else "Ja"
        elif "hdr10+" in sd_type or "2094-40" in sd_type or "smpte2094-40" in sd_type:
            has_hdr10plus = True

    if "dolby" in profile and dv_profile is None:
        dv_profile = "Ja"

    is_hdr = (
        dv_profile is not None
        or has_hdr10plus
        or transfer in {"smpte2084", "arib-std-b67"}
        or primaries in {"bt2020", "bt.2020"}
    )
    return is_hdr, has_hdr10plus, dv_profile


def validate_hdr_flags(
    codec: str,
    bit_depth: int | None,
    pix_fmt: str | None,
    is_hdr: bool,
    has_hdr10plus: bool,
    dv_profile: str | None,
    warnings: list[str],
) -> tuple[bool, bool, str | None]:
    """Apply hard guards to remove impossible HDR/DV false positives."""
    codec_norm = normalize_video_codec(codec)

    if bit_depth is not None and bit_depth < 10:
        if is_hdr or has_hdr10plus or dv_profile:
            warnings.append(
                f"[HDR-Validierung] bit_depth={bit_depth} < 10 "
                f"(codec={codec_norm}, pix_fmt={pix_fmt}) -> "
                "HDR/HDR10+/DV verworfen (verworfener False Positive in Rohdaten)."
            )
        return False, False, None

    if codec_norm == "h264":
        cleared: list[str] = []
        if has_hdr10plus:
            cleared.append("HDR10+")
            has_hdr10plus = False
        if dv_profile:
            cleared.append("DV")
            dv_profile = None
        if is_hdr and (bit_depth is None or bit_depth < 10):
            cleared.append("HDR")
            is_hdr = False
        if cleared:
            warnings.append(
                f"[HDR-Validierung] codec=H.264 -> {', '.join(cleared)} verworfen "
                "(H.264 unterstützt keine HDR10+/DV-Spezialpipeline)."
            )

    # AV1 darf Dolby Vision Profile 10 tragen. Der frühere pauschale Guard,
    # der jedes AV1-DV-Flag verwarf, ist seit dem separaten AV1-DV-Pfad falsch.

    return is_hdr, has_hdr10plus, dv_profile
