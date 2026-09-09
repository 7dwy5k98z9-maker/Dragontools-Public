# -*- coding: utf-8 -*-
from __future__ import annotations

from ..core.models import TargetCodec


HDR10_SETPARAMS_FILTER = (
    "format=p010le,"
    "setparams=range=limited"
    ":colorspace=bt2020nc"
    ":color_primaries=bt2020"
    ":color_trc=smpte2084"
)

DV_P5_LIBPLACEBO_FILTER = (
    "libplacebo=format=p010le"
    ":colorspace=bt2020nc"
    ":color_primaries=bt2020"
    ":color_trc=smpte2084"
    ":range=tv"
)

HDR10_OUTPUT_ARGS = [
    "-color_range", "tv",
    "-color_primaries", "bt2020",
    "-color_trc", "smpte2084",
    "-colorspace", "bt2020nc",
]


def _norm(value: object) -> str:
    return str(value or "").strip().lower().replace(" ", "").replace("_", "").replace("-", "")


def _is_pq(value: object) -> bool:
    text = _norm(value)
    return text in {"pq", "smpte2084"} or "smpte2084" in text


def _is_bt2020(value: object) -> bool:
    return "bt2020" in _norm(value)


def _profile_major(value: object) -> int | None:
    try:
        text = str(value or "").split(".", 1)[0].strip()
        return int(text) if text else None
    except (TypeError, ValueError):
        return None


def source_has_hdr10_base(media_info) -> bool:
    """True when the source should be treated as HDR10-compatible BT.2020/PQ."""
    if media_info is None:
        return False

    dv_profile = (
        _profile_major(getattr(media_info, "dv_profile_major", None))
        or _profile_major(getattr(media_info, "dv_profile", None))
        or _profile_major(getattr(media_info, "dolby_vision_profile", None))
    )
    if getattr(media_info, "dolby_vision", False) and dv_profile in {5, 7, 8}:
        return True

    primary_video = getattr(media_info, "primary_video", None)
    hdr_format = _norm(getattr(primary_video, "hdr_format", None))
    if hdr_format in {"hdr10", "hdr10plus"}:
        return True

    if bool(getattr(media_info, "has_hdr10plus", False)):
        return True

    transfer = (
        getattr(media_info, "transfer_characteristics", None)
        or getattr(primary_video, "color_transfer", None)
    )
    primaries = getattr(primary_video, "color_primaries", None)
    return _is_pq(transfer) and _is_bt2020(primaries)


def should_apply_standard_hdr10_color(media_info, target_codec: str) -> bool:
    codec_value = getattr(target_codec, "value", target_codec)
    codec = str(codec_value).lower()
    return codec in {TargetCodec.H265.value, TargetCodec.AV1.value} and source_has_hdr10_base(media_info)


def hdr10_output_args(media_info, target_codec: str) -> list[str]:
    return list(HDR10_OUTPUT_ARGS) if should_apply_standard_hdr10_color(media_info, target_codec) else []
