# -*- coding: utf-8 -*-
"""Eligibility rules for externally generated HDR10+ metadata.

This module is intentionally Qt- and subprocess-free.  It decides whether a
source may be routed to the optional Dragon HDR10+ Generator.  It does *not*
generate or inject metadata.
"""
from __future__ import annotations

from dataclasses import dataclass

from .codec_utils import normalize_target_codec


def _norm(value: object) -> str:
    return (
        str(value or "")
        .strip()
        .lower()
        .replace("_", "")
        .replace("-", "")
        .replace(".", "")
        .replace(" ", "")
    )


_PQ_TRANSFERS = {
    "pq",
    "st2084",
    "smpte2084",
    "smpte2084pq",
}
_HLG_TRANSFERS = {
    "hlg",
    "aribstdb67",
    "aribstdb67hlg",
}
_BT2020_PRIMARIES = {"bt2020", "rec2020"}


@dataclass(frozen=True, slots=True)
class HDR10PlusGenerationDecision:
    eligible: bool
    code: str
    reason: str


def media_transfer(media_info) -> str:
    video = getattr(media_info, "primary_video", None)
    return str(
        getattr(video, "color_transfer", None)
        or getattr(media_info, "transfer_characteristics", None)
        or ""
    ).strip()


def media_primaries(media_info) -> str:
    video = getattr(media_info, "primary_video", None)
    return str(getattr(video, "color_primaries", None) or "").strip()


def is_pq_transfer(value: object) -> bool:
    return _norm(value) in _PQ_TRANSFERS


def is_hlg_transfer(value: object) -> bool:
    return _norm(value) in _HLG_TRANSFERS


def is_bt2020_primaries(value: object) -> bool:
    return _norm(value) in _BT2020_PRIMARIES


def _dv_profile_major(media_info) -> int | None:
    raw = getattr(media_info, "dv_profile_major", None)
    if raw in (None, ""):
        raw = getattr(media_info, "dv_profile", None)
    if raw in (None, ""):
        return None
    try:
        return int(str(raw).strip().split(".", 1)[0])
    except (TypeError, ValueError):
        return None


def source_is_hdr10_pq_compatible(media_info) -> tuple[bool, str]:
    """Conservatively recognize PQ/HDR10-compatible picture data.

    ``MediaInfo.is_hdr`` is deliberately not used because it also groups HLG,
    Dolby Vision and some BT.2020-only sources together.  Automatic generation
    requires an explicit PQ/ST-2084 transfer characteristic.  If primaries are
    present they must be BT.2020; missing primaries are tolerated because PQ is
    the decisive transfer signal and some otherwise valid sources omit the tag.
    """
    if media_info is None:
        return False, "Medienanalyse fehlt."

    transfer = media_transfer(media_info)
    if is_hlg_transfer(transfer):
        return False, "HLG wird für automatische HDR10+-Erzeugung derzeit nicht unterstützt."
    if not is_pq_transfer(transfer):
        return False, "Quelle verwendet keine PQ/ST2084-Transferfunktion."

    primaries = media_primaries(media_info)
    if primaries and not is_bt2020_primaries(primaries):
        return False, f"PQ-Quelle ist nicht als BT.2020 getaggt ({primaries})."
    return True, "PQ/ST2084-Quelle ist für HDR10+-Analyse geeignet."


def decide_hdr10plus_generation(
    media_info,
    *,
    target_codec: str,
    enabled: bool,
    tool_available: bool,
) -> HDR10PlusGenerationDecision:
    """Return the fail-closed automatic generation decision.

    Existing HDR10+ is always preserved by the established pipeline and is not
    regenerated.  Dolby Vision is accepted only for Profile 8 sources; the DV
    pipeline keeps/injects its RPU separately after HDR10+ generation.
    """
    if not enabled:
        return HDR10PlusGenerationDecision(False, "DISABLED", "Dragon HDR10+ Generator ist deaktiviert.")
    if not tool_available:
        return HDR10PlusGenerationDecision(False, "TOOL_UNAVAILABLE", "Dragon HDR10+ Generator ist nicht verfügbar.")

    has_hdr10plus = bool(
        getattr(media_info, "has_hdrplus", False)
        or getattr(media_info, "has_hdr10plus", False)
    )
    if has_hdr10plus:
        return HDR10PlusGenerationDecision(
            False,
            "HDR10PLUS_PRESENT",
            "Quelle enthält bereits HDR10+; vorhandene Metadaten werden standardmäßig übernommen.",
        )

    if normalize_target_codec(target_codec) != "h265":
        return HDR10PlusGenerationDecision(
            False,
            "UNSUPPORTED_TARGET_CODEC",
            "Automatisch erzeugtes HDR10+ ist derzeit nur für den HEVC/H.265-Pfad freigegeben.",
        )

    pq_ok, pq_reason = source_is_hdr10_pq_compatible(media_info)
    if not pq_ok:
        transfer = media_transfer(media_info)
        code = "SOURCE_HLG" if is_hlg_transfer(transfer) else "SOURCE_NOT_PQ"
        return HDR10PlusGenerationDecision(False, code, pq_reason)

    if bool(getattr(media_info, "has_dv", False)):
        profile = _dv_profile_major(media_info)
        if profile != 8:
            return HDR10PlusGenerationDecision(
                False,
                "DV_PROFILE_NOT_8",
                "Automatische HDR10+-Erzeugung ist mit Dolby Vision zunächst nur für Profil 8.x freigegeben.",
            )

    return HDR10PlusGenerationDecision(True, "ELIGIBLE", pq_reason)


def apply_dv_preservation_guard(
    decision: HDR10PlusGenerationDecision,
    *,
    source_has_dv: bool,
    effective_preserve_dv: bool,
) -> HDR10PlusGenerationDecision:
    """Disable generation rather than silently dropping an existing DV contract."""
    if source_has_dv and decision.eligible and not effective_preserve_dv:
        return HDR10PlusGenerationDecision(
            False,
            "DV_PRESERVATION_REQUIRED",
            "HDR10+-Erzeugung für eine DV-Quelle wird nur zusammen mit Erhalt von Dolby Vision ausgeführt.",
        )
    return decision


__all__ = [
    "HDR10PlusGenerationDecision",
    "apply_dv_preservation_guard",
    "decide_hdr10plus_generation",
    "is_bt2020_primaries",
    "is_hlg_transfer",
    "is_pq_transfer",
    "media_primaries",
    "media_transfer",
    "source_is_hdr10_pq_compatible",
]
