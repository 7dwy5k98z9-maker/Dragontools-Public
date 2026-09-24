# -*- coding: utf-8 -*-
"""Index-, Auswahl- und stabile Reorder-Helfer fuer FileListWidget."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QListWidgetItem

from ..core.path_syntax import path_compare_key


class FileListQueueIndexMixin:
    def set_active_path_checker(self, checker) -> None:
        self._active_path_checker = checker if callable(checker) else None

    def _is_active_path(self, path: str) -> bool:
        checker = self._active_path_checker
        if checker is None:
            return False
        try:
            return bool(checker(path))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False

    def _selected_contains_active_path(self) -> bool:
        return any(
            self._is_active_path(item.data(Qt.ItemDataRole.UserRole))
            for item in self.selectedItems()
        )

    def rebuild_path_index(self) -> None:
        self._path_items = {}
        for i in range(self.count()):
            item = self.item(i)
            if item is None:
                continue
            path = item.data(Qt.ItemDataRole.UserRole)
            if path:
                self._path_items[path_compare_key(str(path))] = item

    def item_for_path(self, path: str):
        key = path_compare_key(path)
        item = self._path_items.get(key)
        if item is not None:
            item_path = item.data(Qt.ItemDataRole.UserRole)
            if item_path and path_compare_key(item_path) == key:
                return item
        self.rebuild_path_index()
        return self._path_items.get(key)

    def selected_paths_in_order(self) -> list[str]:
        return [
            self.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.count())
            if self.item(i) is not None and self.item(i).isSelected()
        ]

    def apply_path_order(self, new_order: list[str]) -> bool:
        current = self.get_paths()
        wanted_keys: list[str] = []
        seen: set[str] = set()
        for path in list(new_order or []) + current:
            key = path_compare_key(path)
            if key and key not in seen:
                wanted_keys.append(key)
                seen.add(key)
        if wanted_keys == [path_compare_key(path) for path in current]:
            return False

        selected_keys = {
            path_compare_key(item.data(Qt.ItemDataRole.UserRole))
            for item in self.selectedItems()
        }
        items_by_key: dict[str, QListWidgetItem] = {}
        while self.count():
            item = self.takeItem(0)
            if item is None:
                continue
            path = item.data(Qt.ItemDataRole.UserRole)
            if path:
                items_by_key[path_compare_key(path)] = item

        for key in wanted_keys:
            item = items_by_key.get(key)
            if item is None:
                continue
            self.addItem(item)
            item.setSelected(key in selected_keys)

        self.rebuild_path_index()
        self.update_empty_banner()
        return True
