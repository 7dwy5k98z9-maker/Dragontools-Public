# -*- coding: utf-8 -*-
from __future__ import annotations

from copy import deepcopy

from .encode_geometry_plan import detect_encode_imax, detect_encode_crop
from .encode_plan import EncodePlan
from .encoder_args import _scale
from .encode_color_plan import build_encode_color_filters, _is_dv5_source
from ..core.models import TargetCodec


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
        self._encoder_options = deepcopy(encoder_options)
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
        active_options = deepcopy(self._encoder_options if encoder_options is None else encoder_options)
        active_scale_mode = scale_mode or self._scale_mode
        active_codec = codec or self._codec
        file_override = deepcopy(file_override)
        imax, src_width, src_height, duration_s = detect_encode_imax(
            input_path, media_info, file_override, active_options,
            detect_imax_auto=self._detect_imax_auto,
            probe_duration_ms=self._probe_duration_ms, log=self._log)
        crop = detect_encode_crop(input_path, pipeline, active_options,
            imax=imax, src_width=src_width, src_height=src_height,
            detected_duration_s=duration_s, detect_crop=self._detect_crop,
            probe_duration_ms=self._probe_duration_ms, log=self._log, logger=self._logger)

        burn_sub_or_vf, sn = self._stream_args.sub_args(input_path, media_info, file_override, container)
        scale_filter = _scale(active_scale_mode)

        color_pre_filter, color_post_filters = build_encode_color_filters(
            media_info, pipeline, active_codec, active_options, logger=self._logger, log=self._log)

        pre_filters = [f for f in [color_pre_filter, crop, scale_filter] if f]
        vf_args = self._stream_args.build_vf_args(
            input_path, output_path, media_info, burn_sub_or_vf, pre_filters,
            post_filters=color_post_filters,
        )
        audio_args = self._stream_args.audio_args(media_info, file_override, container)
        audio_input_args = self._stream_args.audio_input_args(media_info, file_override, container)

        # Preserve the explicit per-file compatibility handoff while keeping
        # defaults untouched and the completed plan independent of its caller.
        if encoder_options is not None:
            encoder_options["_sdr_hdr_applied"] = active_options["_sdr_hdr_applied"]
            if active_options.get("_sdr_hdr_applied"):
                encoder_options["_force_10bit"] = True

        return EncodePlan(
            crop=crop,
            burn_sub_or_vf=burn_sub_or_vf,
            sn=sn,
            vf_args=vf_args,
            audio_args=audio_args,
            audio_input_args=audio_input_args,
            encoder_options=deepcopy(active_options),
        )
