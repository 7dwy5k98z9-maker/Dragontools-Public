"""Validate the HDR10+ per-frame JSON contract independently of generation policy."""
from .strict_numbers import nonnegative_integer

def _int_in_range(value: object, low: int, high: int) -> bool:
    if isinstance(value, bool):
        return False
    try:
        number = nonnegative_integer(value)
    except (TypeError, ValueError):
        return False
    return low <= number <= high

def _numeric_list(value: object, *, length: int | None = None, high: int = 100_000) -> bool:
    if not isinstance(value, list) or (length is not None and len(value) != length):
        return False
    return all(_int_in_range(item, 0, high) for item in value)


def validate_hdr10plus_json_payload(payload: object) -> tuple[bool, str]:
    """Conservatively validate the structural HDR10+ payload contract.

    This is intentionally a compatibility validator, not a second
    ``hdr10plus_tool`` implementation.  It rejects generic JSON, malformed
    per-frame records and clearly impossible ST-2094-40 numeric ranges before
    injection/final comparison while tolerating optional fields emitted by
    different tool versions.
    """

    if not isinstance(payload, dict):
        return False, "HDR10+-JSON muss ein JSON-Objekt sein."
    scene_info = payload.get("SceneInfo")
    if not isinstance(scene_info, list) or not scene_info:
        return False, "HDR10+-JSON enthält keine dynamischen SceneInfo-Daten."

    previous_sequence = -1
    for pos, frame in enumerate(scene_info):
        if not isinstance(frame, dict):
            return False, f"HDR10+-JSON: SceneInfo[{pos}] ist kein Objekt."
        sequence = frame.get("SequenceFrameIndex")
        if sequence is not None:
            if not _int_in_range(sequence, 0, 2_147_483_647):
                return False, f"HDR10+-JSON: ungültiger SequenceFrameIndex in Frame {pos}."
            sequence_i = int(sequence)
            if sequence_i <= previous_sequence:
                return False, "HDR10+-JSON: SequenceFrameIndex ist nicht streng aufsteigend."
            previous_sequence = sequence_i
        windows = frame.get("NumberOfWindows")
        if windows is not None and not _int_in_range(windows, 1, 3):
            return False, f"HDR10+-JSON: NumberOfWindows außerhalb 1..3 in Frame {pos}."

        valid, reason = _validate_luminance(frame, pos)
        if not valid:
            return valid, reason
    return _validate_summary(payload, scene_info)


def _validate_luminance(frame, pos):
    luminance = frame.get("LuminanceParameters")
    if luminance is not None:
        if not isinstance(luminance, dict):
            return False, f"HDR10+-JSON: LuminanceParameters in Frame {pos} sind ungültig."
        average = luminance.get("AverageRGB")
        if average is not None and not _int_in_range(average, 0, 100_000):
            return False, f"HDR10+-JSON: AverageRGB außerhalb 0..100000 in Frame {pos}."
        max_scl = luminance.get("MaxScl")
        if max_scl is not None and not _numeric_list(max_scl, length=3):
            return False, f"HDR10+-JSON: MaxScl ist in Frame {pos} ungültig."
        distributions = luminance.get("LuminanceDistributions")
        if distributions is not None:
            if not isinstance(distributions, dict):
                return False, f"HDR10+-JSON: LuminanceDistributions in Frame {pos} sind ungültig."
            indices = distributions.get("DistributionIndex")
            values = distributions.get("DistributionValues")
            if not isinstance(indices, list) or not isinstance(values, list) or len(indices) != len(values) or not indices:
                return False, f"HDR10+-JSON: DistributionIndex/-Values in Frame {pos} sind inkonsistent."
            if not all(_int_in_range(value, 1, 99) for value in indices):
                return False, f"HDR10+-JSON: DistributionIndex außerhalb 1..99 in Frame {pos}."
            if not all(_int_in_range(value, 0, 100_000) for value in values):
                return False, f"HDR10+-JSON: DistributionValues außerhalb 0..100000 in Frame {pos}."
    return True, ""


def _validate_summary(payload, scene_info):
    summary = payload.get("SceneInfoSummary")
    if summary is not None:
        if not isinstance(summary, dict):
            return False, "HDR10+-JSON enthält eine ungültige SceneInfoSummary."
        counts = summary.get("SceneFrameNumbers")
        starts = summary.get("SceneFirstFrameIndex")
        if counts is not None:
            if not isinstance(counts, list) or not counts or not all(_int_in_range(v, 1, 2_147_483_647) for v in counts):
                return False, "HDR10+-JSON enthält ungültige SceneFrameNumbers."
            if sum(int(v) for v in counts) != len(scene_info):
                return False, "HDR10+-JSON: SceneFrameNumbers stimmen nicht mit SceneInfo überein."
        if starts is not None:
            if not isinstance(starts, list) or not starts or not all(_int_in_range(v, 0, 2_147_483_647) for v in starts):
                return False, "HDR10+-JSON enthält ungültige SceneFirstFrameIndex-Werte."
            starts_i = [int(v) for v in starts]
            if starts_i != sorted(set(starts_i)) or starts_i[0] != 0:
                return False, "HDR10+-JSON: SceneFirstFrameIndex ist nicht eindeutig/aufsteigend ab 0."
        if isinstance(counts, list) and isinstance(starts, list) and len(counts) != len(starts):
            return False, "HDR10+-JSON: Szenenanzahl in Summary-Feldern ist inkonsistent."
    return True, ""


def hdr10plus_summary_frame_count(payload: object) -> int | None:
    """Return the exact frame count encoded by our generator summary, if present."""
    if not isinstance(payload, dict):
        return None
    summary = payload.get("SceneInfoSummary")
    if not isinstance(summary, dict):
        return None
    counts = summary.get("SceneFrameNumbers")
    if not isinstance(counts, list) or not counts:
        return None
    total = 0
    for value in counts:
        try:
            number = nonnegative_integer(value)
        except (TypeError, ValueError):
            return None
        if number <= 0:
            return None
        total += number
    return total or None

