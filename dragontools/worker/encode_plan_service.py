# -*- coding: utf-8 -*-
from __future__ import annotations

from .encode_plan import EncodePlan
from .encoder_args import _scale
from .hdr10_color import (
    DV_P5_LIBPLACEBO_FILTER,
    HDR10_SETPARAMS_FILTER,
    should_apply_standard_hdr10_color,
)
from ..core.models import TargetCodec
from ..core.type_utils import _safe_bool, _safe_int


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


class EncodePlanService:
    """Erzeugt den Encode-Plan für Standard-, DV- und HDR+-Pipelines."""

    def __init__(
        self,
        *,
        codec: str = TargetCodec.H265,
        encoder_options: dict,
        scale_mode: str,
        detect_imax_auto,
        detect_crop,
        probe_duration_ms,
        stream_args_helper,
        log,
        logger,
    ) -> None:
        self._codec = codec
        self._encoder_options = encoder_options
        self._scale_mode = scale_mode
        self._detect_imax_auto = detect_imax_auto
        self._detect_crop = detect_crop
        self._probe_duration_ms = probe_duration_ms
        self._stream_args = stream_args_helper
        self._log = log
        self._logger = logger

    def prepare_encode_plan(
        self,
        input_path: str,
        output_path: str,
        media_info,
        pipeline: str,
        container: str,
        file_override: dict,
        *,
        encoder_options: dict | None = None,
        scale_mode: str | None = None,
        codec: str | None = None,
    ) -> EncodePlan:
        active_options = encoder_options or self._encoder_options
        active_scale_mode = scale_mode or self._scale_mode
        active_codec = codec or self._codec
        imax = _safe_bool(file_override.get("imax"), False)
        video = media_info.primary_video
        src_width = video.width if video else 0
        src_height = video.height if video else 0
        duration_s: float | None = None

        if not imax and _safe_bool(active_options.get("imax_auto_detect"), False):
            duration_s = (self._probe_duration_ms(input_path) or 0) / 1000
            interval_s = _safe_int(active_options.get("imax_probe_interval_s"), 90) or 90
            if self._detect_imax_auto(
                input_path,
                duration_s,
                src_width,
                src_height,
                interval_s,
                _safe_int(active_options.get("imax_probe_duration_s"), 3) or 3,
                _safe_int(active_options.get("imax_min_variance_percent"), 15) or 15,
                _safe_int(active_options.get("imax_min_hits"), 2) or 2,
            ):
                imax = True
                self._log("🎬 IMAX-Auto aktiviert.", "info")

        global_autocrop = _safe_bool(active_options.get("autocrop_enabled"), True)
        crop = None
        if imax:
            self._logger.info("🎬 IMAX: Auto-Crop deaktiviert.")
        elif not global_autocrop:
            self._logger.info("Auto-Crop global deaktiviert.")
        else:
            autocrop_mode = active_options.get("autocrop_mode", "single")
            if autocrop_mode == "multi" and duration_s is None:
                duration_s = (self._probe_duration_ms(input_path) or 0) / 1000
            crop = self._detect_crop(
                input_path,
                src_width,
                src_height,
                autocrop_mode,
                _safe_int(active_options.get("autocrop_probe_start_s"), 30) or 30,
                _safe_int(active_options.get("autocrop_probe_duration_s"), 45) or 45,
                _safe_int(active_options.get("autocrop_probe_interval_s"), 600) or 600,
                duration_s,
            )
            if not crop:
                self._logger.info("Auto-Crop: Keine schwarzen Balken erkannt.")
            elif pipeline == "dv" or str(pipeline).lower() == "pipeline.dv" or getattr(pipeline, "value", None) == "dv" or getattr(pipeline, "name", "").lower() == "dv":
                self._logger.info(f"DV+Crop: {crop} → Level 5 wird in RPU gesetzt.")

        burn_sub_or_vf, sn = self._stream_args.sub_args(input_path, media_info, file_override, container)
        scale_filter = _scale(active_scale_mode)

        # DV Profil 5: Dolby-Vision-Reshaping → BT.2020nc/PQ auch in der Standard-Pipeline.
        # Wenn DV-Erhalt deaktiviert ist und die Quelle DV5 ist, enthalten die Pixel
        # trotzdem Dolby-Vision-P5-Werte. Reines Um-Taggen oder zscale/ictcp reicht
        # in der Praxis nicht zuverlässig und kann Rot→Lila verschieben.
        color_pre_filter = None
        color_post_filters: list[str] = []
        pipeline_value = str(getattr(pipeline, "value", pipeline) or "").strip().lower()
        is_standard_pipeline = pipeline_value not in {"dv", "av1_dv", "pipeline.dv", "pipeline.av1_dv"}
        if is_standard_pipeline and _is_dv5_source(media_info):
            color_pre_filter = DV_P5_LIBPLACEBO_FILTER
            color_post_filters = [HDR10_SETPARAMS_FILTER]
            self._logger.info(
                "⚠️ DV Profil 5 erkannt (ICtCp-Farbraum) – "
                "Farbkorrektur libplacebo aktiv (Dolby Vision P5→BT.2020/PQ)."
            )

        elif is_standard_pipeline and should_apply_standard_hdr10_color(media_info, active_codec):
            color_post_filters = [HDR10_SETPARAMS_FILTER]
            if getattr(media_info, "has_dv", False):
                self._logger.info(
                    "STANDARD-Modus: Dolby Vision wird entfernt; HDR10-Basis "
                    "bleibt als BT.2020/PQ/10-bit getaggt."
                )
            else:
                self._logger.info(
                    "STANDARD-Modus: HDR10-Farbraum wird explizit als "
                    "BT.2020/PQ/10-bit gesetzt."
                )

        pre_filters = [f for f in [color_pre_filter, crop, scale_filter] if f]
        vf_args = self._stream_args.build_vf_args(
            input_path, output_path, media_info, burn_sub_or_vf, pre_filters,
            post_filters=color_post_filters,
        )
        audio_args = self._stream_args.audio_args(media_info, file_override, container)
        audio_input_args = self._stream_args.audio_input_args(media_info, file_override, container)

        return EncodePlan(
            crop=crop,
            burn_sub_or_vf=burn_sub_or_vf,
            sn=sn,
            vf_args=vf_args,
            audio_args=audio_args,
            audio_input_args=audio_input_args,
        )
