# -*- coding: utf-8 -*-
from __future__ import annotations

from ..core.codec_utils import normalize_target_codec


def should_postprocess_generated_hdr10plus(
    *, selection: dict, strip_only: bool, pipeline: str, codec, encoder_options: dict, generate_hdr10plus: bool
) -> bool:
    """Decide if HDR10+ must be generated after an already completed video output."""
    if strip_only:
        return bool(generate_hdr10plus)
    return bool(
        pipeline == "standard"
        and bool((encoder_options or {}).get("_sdr_hdr_applied", False))
        and bool(selection.get("effective_hdr10plus_generator_enabled", False))
        and bool((encoder_options or {}).get("_hdr10plus_generator_available", False))
        and normalize_target_codec(codec) == "h265"
    )


__all__ = ["should_postprocess_generated_hdr10plus"]
