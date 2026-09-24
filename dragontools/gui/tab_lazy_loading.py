# -*- coding: utf-8 -*-
"""Kleine GUI-Helfer für fehlgeschlagene Lazy-Tab-Initialisierung."""
from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget


class TabLoadErrorWidget(QWidget):
    """Fehleransicht eines Lazy-Tabs mit explizitem Wiederholungsversuch."""

    def __init__(
        self,
        *,
        label: str,
        error: BaseException,
        report_path: str | None,
        retry_callback: Callable[..., None],
    ) -> None:
        super().__init__()
        layout = QVBoxLayout(self)

        title = QLabel(f"⚠️  {label} konnte nicht geladen werden.")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size:16px;font-weight:600;")
        layout.addWidget(title)

        detail = QLabel(f"{type(error).__name__}: {error}")
        detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail.setWordWrap(True)
        detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(detail)

        if report_path:
            report = QLabel(f"Fehlerbericht: {report_path}")
            report.setAlignment(Qt.AlignmentFlag.AlignCenter)
            report.setWordWrap(True)
            report.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(report)

        retry = QPushButton("Erneut versuchen")
        retry.setToolTip("Initialisiert diesen Tab erneut. Andere Tabs bleiben unbeeinflusst.")
        retry.clicked.connect(retry_callback)
        layout.addWidget(retry, alignment=Qt.AlignmentFlag.AlignCenter)


def find_tab_index(owner, key: str) -> int:
    """Sucht einen Tab anhand seines stabilen Keys statt eines veralteten Index."""
    for idx in range(owner.tabs.count()):
        if owner.tabs.tabBar().tabData(idx) == key:
            return idx
    return -1


def replace_tab_content(owner, idx: int, widget: QWidget, key: str, label: str) -> None:
    """Ersetzt einen Tab ohne rekursive currentChanged-Ladevorgänge."""
    old_widget = owner.tabs.widget(idx)
    was_current = owner.tabs.currentIndex() == idx
    previous = owner.tabs.blockSignals(True)
    try:
        owner.tabs.removeTab(idx)
        owner.tabs.insertTab(idx, widget, label)
        owner.tabs.tabBar().setTabData(idx, key)
        if was_current:
            owner.tabs.setCurrentIndex(idx)
    finally:
        owner.tabs.blockSignals(previous)
    if old_widget is not None and old_widget is not widget:
        old_widget.deleteLater()


def show_tab_load_error(
    owner,
    *,
    idx: int,
    key: str,
    label: str,
    error: BaseException,
    traceback_text: str,
    logger,
    retry_callback: Callable[..., None],
) -> None:
    """Protokolliert einen Lazy-Load-Fehler und zeigt einen retrybaren Fehler-Tab."""
    logger.exception("Lazy-Tab '%s' (%s) konnte nicht geladen werden", key, label)
    report_path: str | None = None
    try:
        from ..core.gui_error_report import write_tab_load_error_report

        report_path = write_tab_load_error_report(
            tab_key=key,
            tab_label=label,
            error=error,
            traceback_text=traceback_text,
            settings=getattr(owner, "_settings", None),
        )
    except Exception as report_exc:
        logger.warning(
            "Fehlerbericht für Lazy-Tab '%s' konnte nicht geschrieben werden: %s",
            key,
            report_exc,
            exc_info=True,
        )

    # Das Fehlerwidget ist nur Darstellung: None bleibt der Cache-Zustand,
    # damit der Tab explizit erneut initialisiert werden kann.
    owner._tab_widgets[key] = None
    error_widget = TabLoadErrorWidget(
        label=label,
        error=error,
        report_path=report_path,
        retry_callback=retry_callback,
    )
    replace_tab_content(owner, idx, error_widget, key, label)


__all__ = [
    "TabLoadErrorWidget", "find_tab_index", "replace_tab_content",
    "show_tab_load_error",
]
