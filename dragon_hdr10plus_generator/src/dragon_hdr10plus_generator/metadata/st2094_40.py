from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ..analyzer.scanner import FrameStatistics
from ..analyzer.scene_detection import histogram_distance

DISTRIBUTION_INDEX = [1, 5, 10, 25, 50, 75, 90, 95, 99]


@dataclass(frozen=True, slots=True)
class SceneRange:
    scene_id: int
    start: int
    end: int  # exclusive

    @property
    def length(self) -> int:
        return self.end - self.start


def _clamp_int(value: float | int, low: int, high: int) -> int:
    return max(low, min(high, int(round(float(value)))))


def _nits10(value: float) -> int:
    # Classic hdr10plus_tool JSON stores linearized luminance in 0.1 nit units.
    return _clamp_int(max(0.0, value) * 10.0, 0, 100_000)


def detect_scenes(
    frames: Sequence[FrameStatistics],
    *,
    threshold: float = 0.32,
    min_scene_frames: int = 6,
) -> tuple[SceneRange, ...]:
    if not frames:
        return ()
    starts = [0]
    last_start = 0
    minimum = max(1, int(min_scene_frames))
    for previous, current in zip(frames, frames[1:]):
        if current.index - last_start < minimum:
            continue
        if histogram_distance(previous.histogram, current.histogram) >= float(threshold):
            starts.append(current.index)
            last_start = current.index
    starts.append(len(frames))

    # Avoid a tiny tail scene created immediately before EOF.
    if len(starts) >= 3 and starts[-1] - starts[-2] < minimum:
        starts.pop(-2)

    return tuple(
        SceneRange(scene_id=i, start=starts[i], end=starts[i + 1])
        for i in range(len(starts) - 1)
    )


def _average(items: Sequence[float]) -> float:
    return sum(items) / len(items) if items else 0.0


def _scene_luminance_payload(scene_frames: Sequence[FrameStatistics]) -> dict:
    # MaxSCL is scene maximum per RGB component.
    max_scl = [
        max((frame.max_scl_nits[channel] for frame in scene_frames), default=0.0)
        for channel in range(3)
    ]

    # ST-2094-40 distribution semantics for the canonical indices:
    #   1  -> 1% percentile * 10
    #   5  -> DistributionY99: max(scene(frame 99.99% percentile)) * 10
    #   10 -> DistributionY100nit: average percentage <= 100 nits (0..100)
    #   25/50/75/90/95 -> corresponding linear maxRGB percentile * 10
    #   99 -> 99.98% percentile * 10
    distribution_values = [
        _nits10(_average([f.p01_nits for f in scene_frames])),
        _nits10(max((f.p9999_nits for f in scene_frames), default=0.0)),
        _clamp_int(_average([f.below_100_nits_percent for f in scene_frames]), 0, 100),
        _nits10(_average([f.p25_nits for f in scene_frames])),
        _nits10(_average([f.p50_nits for f in scene_frames])),
        _nits10(_average([f.p75_nits for f in scene_frames])),
        _nits10(_average([f.p90_nits for f in scene_frames])),
        _nits10(_average([f.p95_nits for f in scene_frames])),
        _nits10(max((f.p9998_nits for f in scene_frames), default=0.0)),
    ]

    return {
        "AverageRGB": _nits10(_average([f.average_maxrgb_nits for f in scene_frames])),
        "LuminanceDistributions": {
            "DistributionIndex": list(DISTRIBUTION_INDEX),
            "DistributionValues": distribution_values,
        },
        "MaxScl": [_nits10(value) for value in max_scl],
    }


def build_st2094_40_metadata(
    frames: Sequence[FrameStatistics],
    *,
    scene_threshold: float = 0.32,
    min_scene_frames: int = 6,
    tool_name: str = "Dragon HDR10+ Generator",
    tool_version: str = "0.2.0",
) -> dict:
    """Build an hdr10plus_tool-compatible ST-2094-40 Profile-A JSON document.

    Profile A deliberately carries measured luminance statistics only. We do not
    invent Profile-B knee/Bezier tone-mapping curves, whose derivation is a
    separate content-authoring decision. Displays still receive dynamic scene
    luminance metadata and can perform their own HDR10+ tone mapping.
    """
    if not frames:
        raise ValueError("At least one decoded frame is required")

    scenes = detect_scenes(
        frames,
        threshold=scene_threshold,
        min_scene_frames=min_scene_frames,
    )
    scene_info: list[dict] = []
    scene_first: list[int] = []
    scene_counts: list[int] = []

    for scene in scenes:
        subset = frames[scene.start:scene.end]
        luminance = _scene_luminance_payload(subset)
        scene_first.append(scene.start)
        scene_counts.append(scene.length)
        for sequence_index in range(scene.start, scene.end):
            scene_info.append({
                "LuminanceParameters": luminance,
                "NumberOfWindows": 1,
                "TargetedSystemDisplayMaximumLuminance": 0,
                "SceneFrameIndex": sequence_index - scene.start,
                "SceneId": scene.scene_id,
                "SequenceFrameIndex": sequence_index,
            })

    return {
        "JSONInfo": {
            "HDR10plusProfile": "A",
            "Version": "1.0",
        },
        "SceneInfo": scene_info,
        "SceneInfoSummary": {
            "SceneFirstFrameIndex": scene_first,
            "SceneFrameNumbers": scene_counts,
        },
        "ToolInfo": {
            "Tool": tool_name,
            "Version": tool_version,
        },
    }


__all__ = ["DISTRIBUTION_INDEX", "SceneRange", "build_st2094_40_metadata", "detect_scenes"]
