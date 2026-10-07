"""Color and enhancement decisions for an owned encode-plan options tree."""
from __future__ import annotations

from .hdr10_color import dv_p5_libplacebo_filter, hdr10_setparams_filter, should_apply_standard_hdr10_color
from ..core.sdr_hdr_enhancement import decide_sdr_hdr_enhancement


def _is_dv5_source(media_info) -> bool:
    """Gibt True zurück wenn die Quelle DV Profil 5 (ICtCp-Farbraum) ist.

    dv_profile_major liegt auf MediaInfo (nicht VideoStream).
    """
    if media_info is None:
        return False
    return (
        getattr(media_info, "dolby_vision", False) is True
        and getattr(media_info, "dv_profile_major", None) == 5
    )


def build_encode_color_filters(media_info, pipeline, codec, options, *, logger, log):
    # DV Profil 5: Dolby-Vision-Reshaping → BT.2020nc/PQ auch in der Standard-Pipeline.
    # Wenn DV-Erhalt deaktiviert ist und die Quelle DV5 ist, enthalten die Pixel
    # trotzdem Dolby-Vision-P5-Werte. Reines Um-Taggen oder zscale/ictcp reicht
    # in der Praxis nicht zuverlässig und kann Rot→Lila verschieben.
    color_pre_filter = None
    color_post_filters: list[str] = []
    options["_sdr_hdr_applied"] = False
    pipeline_value = str(getattr(pipeline, "value", pipeline) or "").strip().lower()
    is_standard_pipeline = pipeline_value not in {"dv", "av1_dv", "pipeline.dv", "pipeline.av1_dv"}
    if is_standard_pipeline and _is_dv5_source(media_info):
        color_pre_filter = dv_p5_libplacebo_filter(options)
        color_post_filters = [hdr10_setparams_filter(options)]
        logger.info(
            "⚠️ DV Profil 5 erkannt (ICtCp-Farbraum) – "
            "Farbkorrektur libplacebo aktiv (Dolby Vision P5→BT.2020/PQ)."
        )

    elif is_standard_pipeline and should_apply_standard_hdr10_color(media_info, codec):
        color_post_filters = [hdr10_setparams_filter(options)]
        if getattr(media_info, "has_dv", False):
            logger.info(
                "STANDARD-Modus: Dolby Vision wird entfernt; HDR10-Basis "
                "bleibt als BT.2020/PQ/10-bit getaggt."
            )
        else:
            logger.info(
                "STANDARD-Modus: HDR10-Farbraum wird explizit als "
                "BT.2020/PQ/10-bit gesetzt."
            )

    if is_standard_pipeline and not color_pre_filter and not color_post_filters:
        enhancement = decide_sdr_hdr_enhancement(
            media_info,
            target_codec=codec,
            encoder_options=options,
        )
        if enhancement.applied:
            color_post_filters = list(enhancement.filter_chain)
            options["_sdr_hdr_applied"] = True
            options["_force_10bit"] = True
            backend = str(options.get("sdr_hdr_backend", "ffmpeg") or "ffmpeg").strip().lower()
            if backend == "comfyui":
                log(
                    "🧠 SDR→HDR Enhancement aktiv: BT.709 → BT.2020/PQ "
                    "per ComfyUI/HDRTVDM.",
                    "info",
                )
            else:
                log(
                    "🧪 SDR→HDR Enhancement aktiv: BT.709 → BT.2020/PQ per libplacebo "
                    "Inverse Tone Mapping / Range Expansion.",
                    "warn",
                )
        elif enhancement.requested:
            backend = str(options.get("sdr_hdr_backend", "ffmpeg") or "ffmpeg").strip().lower()
            if backend == "comfyui":
                log(
                    f"⚠️ SDR→HDR nicht angewendet: {enhancement.reason} "
                    "Ausgabe bleibt SDR; normaler SDR-Encode wird fortgesetzt.",
                    "warn",
                )
            else:
                log(
                    f"⚠️ SDR→HDR Enhancement übersprungen: {enhancement.reason} "
                    "Normaler SDR-Encode bleibt aktiv.",
                    "warn",
                )

    return color_pre_filter, color_post_filters
