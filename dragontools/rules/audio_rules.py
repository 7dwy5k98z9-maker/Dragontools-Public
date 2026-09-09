# -*- coding: utf-8 -*-
"""Compatibility facade for DragonTools audio rules.

The implementation is split by responsibility:
- audio_rule_basics: parsing, codec helpers, defaults
- audio_rule_migration: config migration/normalization
- audio_rule_repository: cached rule loading
- audio_transcode_policy: channel/transcode decisions
- audio_selection: language/track selection
"""
from __future__ import annotations

from .audio_rule_basics import (
    _DEFAULT_RULES, _channels_for_surround_71_target, _clamp_float, _clamp_int,
    _normalize_copy_range, _normalize_stereo_copy_range,
    _normalize_surround_51_downmix_mode, clamp_audio_target_to_codec_cap,
    max_channels_for_audio_codec, normalize_audio_codec,
    normalize_audio_processing_config, normalize_surround_71_downmix_target,
    safe_float, safe_int,
)
from .audio_rule_migration import _merged_channel_rule, migrate_audio_rules
from .audio_rule_repository import _load_rules, reload_rules
from .audio_selection import (
    _AUDIO_CODEC_RANK, _COMMENTARY_MARKERS, _DESCRIPTIVE_MARKERS,
    _dedupe_audio_streams, _fallback_audio_streams, _has_any_marker,
    _should_skip_for_language_rules, _sort_audio_candidates, _stream_text,
    choose_audio_stream, choose_audio_streams,
)
from .audio_transcode_policy import (
    _channel_rule, _channel_rule_forces_downmix, _force_codec_if_needed_for_channel_cap,
    _passthrough_bitrate_allowed, _stereo_downmix_fallback_codec,
    _surround_51_forces_downmix, _surround_51_target_channels,
    _surround_71_forces_downmix, _surround_71_target_channels,
    _surround_downmix_fallback_codec, audio_requires_transcode,
    default_transcode_target,
)

__all__ = [
    "audio_requires_transcode", "choose_audio_stream", "choose_audio_streams",
    "clamp_audio_target_to_codec_cap", "default_transcode_target",
    "max_channels_for_audio_codec", "migrate_audio_rules", "normalize_audio_codec",
    "normalize_audio_processing_config", "normalize_surround_71_downmix_target",
    "reload_rules", "safe_float", "safe_int",
]
