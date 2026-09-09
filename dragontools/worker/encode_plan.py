# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EncodePlan:
    crop: str | None
    burn_sub_or_vf: object
    sn: list
    vf_args: list
    audio_args: list
    audio_input_args: list = field(default_factory=list)
