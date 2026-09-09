# -*- coding: utf-8 -*-
"""Qt-unabhängige Auswahlregeln für ISO-/MakeMKV-Titel."""
from __future__ import annotations

from statistics import median


def _title_id(title: dict) -> int | None:
    try:
        value = title.get("id")
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _duration(title: dict) -> int:
    try:
        return max(0, int(title.get("duration") or 0))
    except (TypeError, ValueError):
        return 0


def _size(title: dict) -> int:
    try:
        return max(0, int(title.get("size") or 0))
    except (TypeError, ValueError):
        return 0


def choose_main_title(titles: list[dict]) -> int | None:
    """Wählt den längsten Titel; bei gleicher Dauer entscheidet die Größe."""
    candidates = [title for title in titles if _title_id(title) is not None]
    if not candidates:
        return None
    best = max(candidates, key=lambda title: (_duration(title), _size(title)))
    return _title_id(best)


def detect_series_episode_titles(
    titles: list[dict],
    *,
    duration_tolerance: float = 0.15,
    min_episode_count: int = 2,
) -> list[int]:
    """Erkennt eine Gruppe ähnlich langer Titel als Serienepisoden.

    Die Erkennung arbeitet ausschließlich mit MakeMKV-Titelmetadaten und bleibt
    deshalb Qt-unabhängig. Für jeden gültigen Titel wird eine Laufzeitgruppe um
    dessen Dauer gebildet; anschließend wird einmal um den Gruppenmedian
    rezentriert. Gewonnen hat die größte Gruppe. Bei gleicher Gruppengröße wird
    die Gruppe mit längerer Medianlaufzeit bevorzugt, damit kurze Extras nicht
    unnötig vor regulären Episoden gewinnen.

    ``duration_tolerance=0.15`` entspricht ±15 %. Titel ohne positive Laufzeit
    oder ohne gültige ID nehmen nicht an der Serienerkennung teil.
    """
    tolerance = float(duration_tolerance)
    if not 0.0 <= tolerance < 1.0:
        raise ValueError("duration_tolerance muss im Bereich 0.0 <= x < 1.0 liegen")
    minimum = max(2, int(min_episode_count))

    valid: list[tuple[int, int, int]] = []
    seen_ids: set[int] = set()
    for title in titles:
        title_id = _title_id(title)
        duration = _duration(title)
        if title_id is None or duration <= 0 or title_id in seen_ids:
            continue
        seen_ids.add(title_id)
        valid.append((title_id, duration, _size(title)))

    if len(valid) < minimum:
        return []

    def within(value: int, center: float) -> bool:
        return abs(value - center) <= center * tolerance

    groups: dict[tuple[int, ...], tuple[list[tuple[int, int, int]], float]] = {}
    for _title_id_value, anchor_duration, _title_size in valid:
        first = [entry for entry in valid if within(entry[1], anchor_duration)]
        if len(first) < minimum:
            continue
        center = float(median(entry[1] for entry in first))
        group = [entry for entry in valid if within(entry[1], center)]
        if len(group) < minimum:
            continue
        key = tuple(sorted(entry[0] for entry in group))
        groups[key] = (group, center)

    if not groups:
        return []

    group, _center = max(
        groups.values(),
        key=lambda item: (
            len(item[0]),
            item[1],
            sum(entry[2] for entry in item[0]),
        ),
    )
    return [entry[0] for entry in sorted(group, key=lambda entry: entry[0])]


def choose_auto_titles(
    titles: list[dict],
    *,
    detect_series_disc: bool = True,
    duration_tolerance: float = 0.15,
) -> tuple[list[int], bool]:
    """Liefert automatische Titel-IDs und ob eine Serien-Disc erkannt wurde."""
    if detect_series_disc:
        episodes = detect_series_episode_titles(
            titles,
            duration_tolerance=duration_tolerance,
        )
        if episodes:
            return episodes, True

    main_title = choose_main_title(titles)
    return ([main_title] if main_title is not None else []), False


__all__ = ["choose_auto_titles", "choose_main_title", "detect_series_episode_titles"]
