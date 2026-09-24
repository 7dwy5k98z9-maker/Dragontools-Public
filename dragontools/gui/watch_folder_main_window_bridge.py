# -*- coding: utf-8 -*-
"""Functional bridge between MainWindow and WatchFolderController.

Kept outside MainWindow action mixins so their stable public/private method contract does not grow.
"""
from __future__ import annotations

import logging

from .watch_folder_controller import WatchFolderController
from .tab_lazy_loading import find_tab_index

_LOG = logging.getLogger(__name__)


def start_watch_folder_controller(window) -> None:
    window._watch_folder_controller = WatchFolderController(
        settings=window._settings,
        enqueue_callback=lambda **kwargs: enqueue_watch_folder_files(window, **kwargs),
        status_callback=lambda text: window.statusBar().showMessage(text, 5000),
        parent=window,
    )


def refresh_watch_folder_controller(window) -> None:
    controller = getattr(window, "_watch_folder_controller", None)
    if controller is not None:
        controller.refresh_settings()


def stop_watch_folder_controller(window) -> bool:
    controller = getattr(window, "_watch_folder_controller", None)
    if controller is None:
        return True
    return bool(controller.stop())


def enqueue_watch_folder_files(
    window,
    *,
    codec: str,
    paths: list[str],
    profile_key: str = "",
    auto_start: bool = True,
    completion_callback=None,
) -> list[str]:
    widget = getattr(window, "_tab_widgets", {}).get(codec)
    if widget is None:
        idx = find_tab_index(window, codec)
        if idx >= 0:
            # currentChanged is already wired to the normal lazy-loader. Emitting the
            # public signal loads the requested converter without switching the visible tab.
            window.tabs.currentChanged.emit(idx)
            widget = getattr(window, "_tab_widgets", {}).get(codec)
    if widget is None:
        _LOG.info("Watch-Folder wartet auf nicht verfügbaren Converter-Tab %s", codec)
        window.statusBar().showMessage(
            f"Watch-Folder wartet: Converter-Tab {codec.upper()} ist ausgeblendet oder konnte nicht geladen werden.", 7000
        )
        return []
    enqueue = getattr(widget, "enqueue_watch_folder_files", None)
    if not callable(enqueue):
        return []
    return list(
        enqueue(
            paths,
            profile_key=profile_key,
            auto_start=auto_start,
            completion_callback=completion_callback,
        )
        or []
    )


__all__ = [
    "start_watch_folder_controller", "refresh_watch_folder_controller",
    "stop_watch_folder_controller", "enqueue_watch_folder_files",
]
