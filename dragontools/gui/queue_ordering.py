# -*- coding: utf-8 -*-
"""Qt-unabhängige Reihenfolgelogik für die Konverter-Warteschlange."""
from __future__ import annotations

from ..core.path_syntax import path_compare_key

MOVE_UP = "up"
MOVE_DOWN = "down"
MOVE_FRONT = "front"
MOVE_BACK = "back"
_VALID_ACTIONS = {MOVE_UP, MOVE_DOWN, MOVE_FRONT, MOVE_BACK}


def reorder_selected_paths(
    paths: list[str],
    selected_paths: list[str],
    active_paths: list[str] | set[str] | tuple[str, ...] = (),
    *,
    action: str,
) -> list[str]:
    """Ordnet ausgewählte, nicht aktive Queue-Einträge stabil neu.

    ``front`` setzt die Auswahl direkt hinter den letzten aktuell laufenden
    Eintrag. Laufende Einträge selbst werden nie als verschiebbare Auswahl
    behandelt. Die relative Reihenfolge einer Mehrfachauswahl bleibt erhalten.
    """
    if action not in _VALID_ACTIONS:
        raise ValueError(f"Unbekannte Queue-Aktion: {action}")

    order = list(paths or [])
    if len(order) < 2:
        return order

    selected_keys = {path_compare_key(path) for path in selected_paths or []}
    active_keys = {path_compare_key(path) for path in active_paths or []}
    movable_keys = selected_keys - active_keys
    if not movable_keys:
        return order

    if action == MOVE_UP:
        result = list(order)
        for idx in range(1, len(result)):
            current_key = path_compare_key(result[idx])
            previous_key = path_compare_key(result[idx - 1])
            if (
                current_key in movable_keys
                and previous_key not in movable_keys
                and previous_key not in active_keys
            ):
                result[idx - 1], result[idx] = result[idx], result[idx - 1]
        return result

    if action == MOVE_DOWN:
        result = list(order)
        for idx in range(len(result) - 2, -1, -1):
            current_key = path_compare_key(result[idx])
            next_key = path_compare_key(result[idx + 1])
            if (
                current_key in movable_keys
                and next_key not in movable_keys
                and next_key not in active_keys
            ):
                result[idx], result[idx + 1] = result[idx + 1], result[idx]
        return result

    selected = [path for path in order if path_compare_key(path) in movable_keys]
    remaining = [path for path in order if path_compare_key(path) not in movable_keys]

    if action == MOVE_BACK:
        return remaining + selected

    active_indexes = [
        idx for idx, path in enumerate(remaining)
        if path_compare_key(path) in active_keys
    ]
    insert_at = (max(active_indexes) + 1) if active_indexes else 0
    return remaining[:insert_at] + selected + remaining[insert_at:]
