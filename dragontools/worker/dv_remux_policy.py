# -*- coding: utf-8 -*-
"""Policy decisions for the explicit Dolby-Vision remux workflow."""
from __future__ import annotations

from dataclasses import dataclass

from .dv_pipeline_context import normalize_dv_profile_major


@dataclass(frozen=True, slots=True)
class DVRemuxDecision:
    action: str
    source_profile_major: int | None
    expected_profile_major: int | None
    reason: str = ""
    warning: str = ""

    @property
    def should_normalize_to_p81(self) -> bool:
        return self.action == "normalize_p81"

    @property
    def should_encode(self) -> bool:
        return self.action == "encode"

    @property
    def should_skip(self) -> bool:
        return self.action == "skip"


def decide_dv_remux(
    media_info,
    *,
    container: str,
    keep_dv7_mkv: bool,
    encode_dv5: bool,
) -> DVRemuxDecision:
    """Return one deterministic action for a DV-remux source.

    Policy:
      * P5: encode through the normal H.265 DV pipeline or skip.
      * P7 -> MP4: always normalize to P8.1.
      * P7 -> MKV: keep P7 only when explicitly requested, otherwise P8.1.
      * P8 -> MP4: normalize through mode 2 so ``dvp=8.1.hdr10`` describes
        the actual prepared bitstream instead of merely relabelling it.
      * P8 -> MKV: keep the existing P8 stream.
      * non-DV/unknown profiles: fail closed / skip.
    """
    target = str(container or "mp4").strip().lower()
    profile = normalize_dv_profile_major(media_info)
    has_dv = bool(
        getattr(media_info, "has_dv", False)
        or getattr(media_info, "dolby_vision", False)
        or profile is not None
    )
    if not has_dv:
        return DVRemuxDecision(
            "skip", profile, None,
            "Keine Dolby-Vision-Metadaten erkannt; DV-Remux wird nicht ausgeführt.",
        )

    if profile == 5:
        if encode_dv5:
            return DVRemuxDecision(
                "encode", 5, 8,
                "Dolby Vision Profil 5 benötigt den normalen DV-Encodingpfad.",
            )
        return DVRemuxDecision(
            "skip", 5, None,
            "Dolby Vision Profil 5 erkannt und automatisches Encoding ist deaktiviert.",
        )

    if profile == 7:
        if target == "mkv" and keep_dv7_mkv:
            return DVRemuxDecision(
                "remux", 7, 7,
                "DV7 wird gemäß Einstellung im MKV unverändert beibehalten.",
            )
        target_label = "MP4" if target == "mp4" else "MKV"
        return DVRemuxDecision(
            "normalize_p81", 7, 8,
            f"DV7 wird für den {target_label}-Remux mit dovi_tool Mode 2 nach DV 8.1 normalisiert.",
            "Beim P7→P8.1-Schritt wird der Enhancement Layer verworfen; bei FEL kann dadurch zusätzliche Bildinformation verloren gehen.",
        )

    if profile == 8:
        if target == "mp4":
            return DVRemuxDecision(
                "normalize_p81", 8, 8,
                "DV8 wird vor dem MP4-Mux mit dovi_tool Mode 2 auf einen P8.1-kompatiblen Bitstream normalisiert.",
            )
        return DVRemuxDecision(
            "remux", 8, 8,
            "DV8 wird im MKV ohne Profilumschreibung remuxt.",
        )

    return DVRemuxDecision(
        "skip", profile, None,
        f"Dolby-Vision-Profil {profile if profile is not None else 'unbekannt'} wird vom DV-Remux nicht sicher unterstützt.",
    )
