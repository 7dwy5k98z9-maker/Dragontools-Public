# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EncoderSettingsState:
    loading: bool = False
    encoder_key: str = "cpu"
    crf: int = 22
    preset: str = "medium"
    scale: str = "original"
    strip_only: bool = False
    overwrite_original: bool = False
    move: bool = False
    shutdown: bool = False
    autocrop_enabled: bool = True
    imax_auto_detect: bool = False
    imax_probe_interval_s: int = 90
    preserve_dv: bool = True
    preserve_hdrplus: bool = True
    encoder_options: dict = field(default_factory=dict)
