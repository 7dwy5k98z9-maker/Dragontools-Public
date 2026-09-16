# -*- coding: utf-8 -*-
"""Video-part verification for expected media contracts."""
from __future__ import annotations

from dataclasses import dataclass
import re

from ..core.media_metadata import normalize_video_codec
from .media_contract_types import ExpectedMediaContract


@dataclass(frozen=True)
class VideoContractEvaluation:
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    non_geometry_errors: tuple[str, ...]
    geometry_errors: tuple[str, ...]
    expected_width: int | None
    expected_height: int | None
    actual_width: int | None
    actual_height: int | None
    geometry_max_delta: int
    geometry_severity: str


def _dimension_delta(expected: int | None, actual: int) -> int:
    if expected is None:
        return 0
    if actual <= 0:
        return max(5, abs(int(expected)))
    return abs(int(actual) - int(expected))


def _geometry_severity(delta: int) -> str:
    if delta <= 0:
        return "exact"
    if delta <= 2:
        return "minor"
    if delta <= 4:
        return "review"
    return "major"


def _dimension_message(label: str, expected: int, actual: int, delta: int, *, warning: bool) -> str:
    prefix = "WARNUNG" if warning else "FEHLER"
    actual_text = str(actual) if actual > 0 else "<unbekannt>"
    return (
        f"{prefix}: Video-{label} abweichend: erwartet {expected}, gefunden {actual_text} "
        f"(Differenz {delta} Pixel)."
    )


def video_bit_depth(stream: dict) -> int | None:
    try:
        value = int(stream.get("bits_per_raw_sample"))
        if value > 0:
            return value
    except (TypeError, ValueError):
        pass
    pix_fmt = str(stream.get("pix_fmt") or "").lower()
    match = re.search(r"(?:p|p0|yuv\d+p)(10|12|14|16)(?:le|be)?$", pix_fmt)
    if match:
        return int(match.group(1))
    if "10" in pix_fmt:
        return 10
    if "12" in pix_fmt:
        return 12
    return 8 if pix_fmt else None


def evaluate_video_contract(contract: ExpectedMediaContract, streams: list[dict]) -> VideoContractEvaluation:
    non_geometry_errors: list[str] = []
    geometry_errors: list[str] = []
    warnings: list[str] = []

    if len(streams) != contract.video_stream_count:
        non_geometry_errors.append(
            f"Videostream-Anzahl abweichend: erwartet {contract.video_stream_count}, gefunden {len(streams)}."
        )
    if not streams:
        return VideoContractEvaluation(
            errors=tuple(non_geometry_errors),
            warnings=(),
            non_geometry_errors=tuple(non_geometry_errors),
            geometry_errors=(),
            expected_width=contract.expected_width,
            expected_height=contract.expected_height,
            actual_width=None,
            actual_height=None,
            geometry_max_delta=0,
            geometry_severity="exact",
        )

    video = streams[0]
    actual_codec = normalize_video_codec(video.get("codec_name"))
    expected_codec = normalize_video_codec(contract.video_codec)
    if expected_codec and actual_codec != expected_codec:
        non_geometry_errors.append(
            f"Videocodec abweichend: erwartet {expected_codec}, gefunden {actual_codec or '<unbekannt>'}."
        )
    if contract.min_video_bit_depth is not None:
        depth = video_bit_depth(video)
        if depth is None or depth < contract.min_video_bit_depth:
            non_geometry_errors.append(
                f"Video-Bittiefe abweichend: mindestens {contract.min_video_bit_depth} Bit erwartet, "
                f"gefunden {depth if depth is not None else '<unbekannt>'}."
            )

    try:
        width, height = int(video.get("width") or 0), int(video.get("height") or 0)
    except (TypeError, ValueError):
        width = height = 0

    deltas: list[int] = []
    for label, expected, actual in (
        ("Breite", contract.expected_width, width),
        ("Hoehe", contract.expected_height, height),
    ):
        if expected is None:
            continue
        delta = _dimension_delta(expected, actual)
        deltas.append(delta)
        if delta == 0:
            continue
        # 1-2 px are a warning only. The workflow performs an additional
        # Dolby-Vision RPU alignment check before allowing replacement.
        if delta <= 2:
            warnings.append(_dimension_message(label, int(expected), actual, delta, warning=True))
        else:
            geometry_errors.append(_dimension_message(label, int(expected), actual, delta, warning=False))

    max_delta = max(deltas, default=0)
    errors = non_geometry_errors + geometry_errors
    return VideoContractEvaluation(
        errors=tuple(errors),
        warnings=tuple(warnings),
        non_geometry_errors=tuple(non_geometry_errors),
        geometry_errors=tuple(geometry_errors),
        expected_width=contract.expected_width,
        expected_height=contract.expected_height,
        actual_width=width or None,
        actual_height=height or None,
        geometry_max_delta=max_delta,
        geometry_severity=_geometry_severity(max_delta),
    )


def verify_video_contract(contract: ExpectedMediaContract, streams: list[dict]) -> list[str]:
    """Compatibility API: returns blocking contract errors only."""
    return list(evaluate_video_contract(contract, streams).errors)
