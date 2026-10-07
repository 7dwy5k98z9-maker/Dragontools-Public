"""Reject invalid numeric evidence before building audio timing filters."""
import math


def finite_number(value):
    if isinstance(value, bool):
        raise ValueError("Boolean is not timing evidence")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Audio timing must be finite")
    return number


def positive_tempo(value):
    number = finite_number(value)
    if number <= 0:
        raise ValueError("Audio tempo must be positive")
    return number


def mapping_error(mapping):
    try:
        positive_tempo(mapping.speed_factor)
        finite_number(mapping.offset_s)
        positive_tempo(mapping.source_info.duration_s)
        positive_tempo(mapping.target_info.duration_s)
    except (TypeError, ValueError, OverflowError):
        return "Ungültige oder nicht endliche Audio-Zeitdaten."
    return ""


def valid_landmarks(points, source_info, target_info):
    try:
        source_duration = positive_tempo(source_info.duration_s)
        target_duration = positive_tempo(target_info.duration_s)
        reference = [finite_number(p.reference_time_s) for p in points]
        matched = [finite_number(p.matched_time_s) for p in points]
        quality = [finite_number(p.similarity) for p in points]
        return (
            all(0 <= t <= target_duration for t in reference)
            and all(0 <= t <= source_duration for t in matched)
            and all(0 <= q <= 1 for q in quality)
            and all(a < b for a, b in zip(reference, reference[1:]))
            and all(a < b for a, b in zip(matched, matched[1:]))
        )
    except (TypeError, ValueError, OverflowError):
        return False


def cuts_error(mapping, cuts):
    previous_target = previous_source = 0.0
    try:
        for cut in sorted(cuts, key=lambda item: item.target_start_s):
            target_start, target_end, source_start, source_end = (
                finite_number(value) for value in (cut.target_start_s, cut.target_end_s,
                    cut.source_start_s, cut.source_end_s))
            if not (previous_target <= target_start < target_end <= mapping.target_info.duration_s
                    and previous_source <= source_start < source_end <= mapping.source_info.duration_s):
                return "Audio-Schnittbereiche überlappen, liegen außerhalb der Datei oder vertauschen die Zeitfolge."
            previous_target, previous_source = target_end, source_end
    except (TypeError, ValueError, OverflowError):
        return "Ungültige oder nicht endliche Audio-Schnittdaten."
    return ""
