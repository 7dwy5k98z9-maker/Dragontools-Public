# -*- coding: utf-8 -*-
"""Structured frame-count evidence shared by DV/HDR10+ pipeline stages.

The model deliberately avoids content hashing.  A lightweight stream identity
(path + size + mtime_ns) is sufficient to reject stale evidence without adding
another full-file read to long HEVC intermediates.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Literal
from ..core.strict_numbers import positive_integer

FrameCountReliability = Literal["unknown", "estimated", "reliable"]
TemporalMapping = Literal["preserved", "changed", "unknown"]


@dataclass(frozen=True, slots=True)
class StreamIdentity:
    path: str
    size: int | None
    mtime_ns: int | None
    device: int | None = None
    inode: int | None = None
    ctime_ns: int | None = None

    @classmethod
    def capture(cls, path: str | Path) -> "StreamIdentity":
        target = Path(path)
        try:
            stat = target.stat()
        except OSError:
            return cls(str(target), None, None)
        return cls(str(target), int(stat.st_size), int(stat.st_mtime_ns),
                   int(stat.st_dev), int(stat.st_ino), int(stat.st_ctime_ns))

    def matches(self, path: str | Path) -> bool:
        other = self.capture(path)
        return (
            self.path == other.path
            and self.size is not None
            and self.mtime_ns is not None
            and self.size == other.size
            and self.mtime_ns == other.mtime_ns
            and self.device == other.device and self.inode == other.inode
            and self.ctime_ns == other.ctime_ns
        )


@dataclass(frozen=True, slots=True)
class FrameCountEvidence:
    count: int | None
    source: str
    reliability: FrameCountReliability
    stream: StreamIdentity
    stage: str
    temporal_mapping: TemporalMapping = "unknown"

    @classmethod
    def reliable(
        cls,
        count: int,
        *,
        source: str,
        path: str | Path,
        stage: str,
        temporal_mapping: TemporalMapping = "unknown",
    ) -> "FrameCountEvidence":
        value = positive_integer(count)
        if value <= 0:
            raise ValueError("Reliable frame count must be > 0")
        return cls(
            value,
            str(source),
            "reliable",
            StreamIdentity.capture(path),
            str(stage),
            temporal_mapping,
        )

    @classmethod
    def estimated(
        cls,
        count: int,
        *,
        source: str,
        path: str | Path,
        stage: str,
    ) -> "FrameCountEvidence":
        value = positive_integer(count)
        if value <= 0:
            raise ValueError("Estimated frame count must be > 0")
        return cls(value, str(source), "estimated", StreamIdentity.capture(path), str(stage), "unknown")

    @classmethod
    def unknown(cls, *, source: str, path: str | Path, stage: str) -> "FrameCountEvidence":
        return cls(None, str(source), "unknown", StreamIdentity.capture(path), str(stage), "unknown")

    def is_current_for(self, path: str | Path) -> bool:
        return self.stream.matches(path)

    def is_reliable_for(self, path: str | Path) -> bool:
        return bool(
            self.reliability == "reliable"
            and self.count is not None
            and self.count > 0
            and self.is_current_for(path)
        )

    def derive_for_metadata_only_output(
        self,
        output_path: str | Path,
        *,
        source: str,
        stage: str,
    ) -> "FrameCountEvidence":
        """Carry a reliable count across a frame-preserving metadata injection."""
        if not self.is_reliable_for(self.stream.path):
            return FrameCountEvidence.unknown(source=source, path=output_path, stage=stage)
        return FrameCountEvidence.reliable(
            self.count,
            source=source,
            path=output_path,
            stage=stage,
            temporal_mapping=self.temporal_mapping,
        )


def temporal_mapping_for_filters(vf_args: list[object] | tuple[object, ...] | None) -> TemporalMapping:
    """Classify whether a filter plan can alter frame count/order/timing.

    Crop/scale/colorspace/subtitle filters preserve presentation-frame identity.
    Explicit temporal filters are fail-closed because equal counts alone do not
    prove RPU alignment after drops/duplicates/interpolation/timestamp rewrites.
    """
    args = [str(item or "").lower() for item in (vf_args or ())]
    if any(item.split(":", 1)[0] in {"-r", "-ss", "-sseof", "-t", "-to", "-frames", "-vframes", "-shortest"} for item in args):
        return "changed"
    text = re.sub(r'@[-a-z0-9_]+(?=\s*=)', '', " ".join(args))
    temporal_tokens = (
        "fps=", "framerate=", "minterpolate", "framestep", "select=",
        "setpts=", "mpdecimate", "decimate", "fieldmatch", "telecine",
        "pullup", "tblend=all_mode=average",
        "reverse", "tpad=", "trim=", "shuffleframes=", "loop=",
        "bwdif", "yadif", "separatefields", "interleave", "concat=", "tmix=",
    )
    if any(token in text for token in temporal_tokens):
        return "changed"
    return "preserved"


__all__ = [
    "FrameCountEvidence",
    "FrameCountReliability",
    "StreamIdentity",
    "TemporalMapping",
    "temporal_mapping_for_filters",
]
