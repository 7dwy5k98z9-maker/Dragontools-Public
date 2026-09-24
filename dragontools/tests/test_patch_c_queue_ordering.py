from __future__ import annotations

from dragontools.gui.queue_ordering import (
    MOVE_BACK,
    MOVE_DOWN,
    MOVE_FRONT,
    MOVE_UP,
    reorder_selected_paths,
)


def test_move_up_preserves_multi_selection_order_and_stops_at_active_item():
    paths = ["active.mkv", "a.mkv", "b.mkv", "c.mkv", "d.mkv"]
    result = reorder_selected_paths(
        paths,
        ["c.mkv", "d.mkv"],
        ["active.mkv"],
        action=MOVE_UP,
    )
    assert result == ["active.mkv", "a.mkv", "c.mkv", "d.mkv", "b.mkv"]


def test_move_down_preserves_multi_selection_order():
    paths = ["active.mkv", "a.mkv", "b.mkv", "c.mkv", "d.mkv"]
    result = reorder_selected_paths(
        paths,
        ["a.mkv", "b.mkv"],
        ["active.mkv"],
        action=MOVE_DOWN,
    )
    assert result == ["active.mkv", "c.mkv", "a.mkv", "b.mkv", "d.mkv"]


def test_move_front_places_selection_directly_after_all_active_jobs():
    paths = ["active1.mkv", "active2.mkv", "a.mkv", "b.mkv", "c.mkv", "d.mkv"]
    result = reorder_selected_paths(
        paths,
        ["d.mkv", "b.mkv"],
        ["active1.mkv", "active2.mkv"],
        action=MOVE_FRONT,
    )
    assert result == ["active1.mkv", "active2.mkv", "b.mkv", "d.mkv", "a.mkv", "c.mkv"]


def test_move_back_places_selection_at_end_and_keeps_selection_order():
    paths = ["active.mkv", "a.mkv", "b.mkv", "c.mkv", "d.mkv"]
    result = reorder_selected_paths(
        paths,
        ["b.mkv", "d.mkv"],
        ["active.mkv"],
        action=MOVE_BACK,
    )
    assert result == ["active.mkv", "a.mkv", "c.mkv", "b.mkv", "d.mkv"]


def test_active_selected_item_is_never_moved():
    paths = ["active.mkv", "a.mkv", "b.mkv"]
    result = reorder_selected_paths(
        paths,
        ["active.mkv", "b.mkv"],
        ["active.mkv"],
        action=MOVE_FRONT,
    )
    assert result == ["active.mkv", "b.mkv", "a.mkv"]


def test_invalid_action_is_rejected():
    try:
        reorder_selected_paths(["a.mkv", "b.mkv"], ["b.mkv"], action="sideways")
    except ValueError as exc:
        assert "Unbekannte Queue-Aktion" in str(exc)
    else:
        raise AssertionError("invalid action must raise ValueError")
