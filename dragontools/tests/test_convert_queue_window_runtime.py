from __future__ import annotations

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QListWidgetItem

from dragontools.gui.convert_queue_window import ConvertQueueWindow
from dragontools.gui.convert_widget_file_queue import FileListWidget


def _add_owner_row(source_list: FileListWidget, path: str) -> None:
    item = QListWidgetItem(path)
    item.setData(Qt.ItemDataRole.UserRole, path)
    source_list.addItem(item)


def _window(qtbot, *, paths: list[str]):
    source_list = FileListWidget()
    qtbot.addWidget(source_list)
    for path in paths:
        _add_owner_row(source_list, path)

    applied: list[list[str]] = []
    window = ConvertQueueWindow(
        None,
        default_codec="h265",
        source_list=source_list,
        is_queue_blocking_move_active=lambda: False,
        active_worker=lambda: None,
        apply_queue_order=lambda order: applied.append(list(order)),
        toggle_pause=lambda: None,
        abort=lambda: None,
        on_closed=lambda: None,
    )
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(10)
    return window, applied


def test_zoom_queue_window_shows_up_and_down_buttons(qtbot):
    window, _applied = _window(qtbot, paths=["a.mkv", "b.mkv", "c.mkv"])

    assert window.up_btn.isVisible()
    assert window.down_btn.isVisible()
    assert window.up_btn.text() == "↑"
    assert window.down_btn.text() == "↓"
    assert "oben" in window.up_btn.toolTip().lower()
    assert "unten" in window.down_btn.toolTip().lower()


def test_zoom_queue_up_and_down_buttons_apply_same_ordering_rules(qtbot):
    window, applied = _window(qtbot, paths=["a.mkv", "b.mkv", "c.mkv"])

    middle = window.file_list.item(1)
    middle.setSelected(True)
    window.file_list.setCurrentItem(middle)

    qtbot.mouseClick(window.up_btn, Qt.MouseButton.LeftButton)
    assert applied[-1] == ["b.mkv", "a.mkv", "c.mkv"]
    assert window.file_list.get_paths() == ["b.mkv", "a.mkv", "c.mkv"]

    window.file_list.clearSelection()
    moved = window.file_list.item(0)
    moved.setSelected(True)
    window.file_list.setCurrentItem(moved)
    qtbot.mouseClick(window.down_btn, Qt.MouseButton.LeftButton)
    assert applied[-1] == ["a.mkv", "b.mkv", "c.mkv"]
    assert window.file_list.get_paths() == ["a.mkv", "b.mkv", "c.mkv"]


def test_zoom_queue_reorder_buttons_disable_while_move_blocks_queue(qtbot):
    source_list = FileListWidget()
    qtbot.addWidget(source_list)
    _add_owner_row(source_list, "a.mkv")
    window = ConvertQueueWindow(
        None,
        default_codec="h265",
        source_list=source_list,
        is_queue_blocking_move_active=lambda: True,
        active_worker=lambda: None,
        apply_queue_order=lambda _order: None,
        toggle_pause=lambda: None,
        abort=lambda: None,
        on_closed=lambda: None,
    )
    qtbot.addWidget(window)
    window.show()
    window.refresh_from_owner()

    assert not window.front_btn.isEnabled()
    assert not window.up_btn.isEnabled()
    assert not window.down_btn.isEnabled()
    assert not window.back_btn.isEnabled()
