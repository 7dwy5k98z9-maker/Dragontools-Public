# -*- coding: utf-8 -*-
"""Candidate selector used by the movie/series renamer table."""
from __future__ import annotations

import logging

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import QComboBox, QSizePolicy


_LOG = logging.getLogger(__name__)


class WideCandidateComboBox(QComboBox):
    """Show wide candidate popups without widening the main window.

    The table cell defines the visible combo width.  Long metadata labels are
    presentation data and must therefore not contribute a horizontal minimum
    size to the surrounding table/QMainWindow hierarchy.
    """

    _POPUP_HORIZONTAL_PADDING = 56
    _LAYOUT_SIZE_HINT_WIDTH = 240

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.setMinimumContentsLength(1)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        return QSize(0, hint.height())

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        return QSize(min(hint.width(), self._LAYOUT_SIZE_HINT_WIDTH), hint.height())

    def showPopup(self) -> None:
        """Resize only the transient popup, never the combo/view minimum size."""
        desired_width = self.width()
        try:
            view = self.view()
            metrics = view.fontMetrics()
            content_width = max(
                (metrics.horizontalAdvance(self.itemText(index)) for index in range(self.count())),
                default=self.width(),
            )
            desired_width = max(
                self.width(), content_width + self._POPUP_HORIZONTAL_PADDING
            )

            screen = self.screen()
            if screen is not None:
                available = screen.availableGeometry()
                desired_width = min(
                    desired_width, max(self.width(), available.width() - 40)
                )

            view.setTextElideMode(Qt.TextElideMode.ElideNone)
        except Exception:
            _LOG.debug(
                "Unterdrückte Best-Effort-Ausnahme bei der "
                "Renamer-Popup-Breitenberechnung.",
                exc_info=True,
            )

        super().showPopup()

        try:
            popup = self.view().window()
            if popup is not None and popup is not self.window():
                popup.resize(int(desired_width), popup.height())
        except Exception:
            _LOG.debug(
                "Renamer-Popup konnte nicht auf die Wunschbreite gesetzt werden.",
                exc_info=True,
            )
