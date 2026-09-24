from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ToneMappingCurve:
    knee_x: float
    knee_y: float
    bezier_anchors: tuple[float, ...]


def derive_tone_mapping_curve(*_args, **_kwargs) -> ToneMappingCurve:
    raise NotImplementedError(
        "Knee point and Bezier derivation require validated ST-2094-40 analysis"
    )


__all__ = ["ToneMappingCurve", "derive_tone_mapping_curve"]
