from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QLineEdit, QListWidget, QProgressBar, QPushButton, QTextEdit, QWidget

from .iso_widget_inputs import ISOWidgetInputMixin
from .iso_widget_runtime import ISOWidgetRuntimeMixin
from .iso_widget_view import ISOWidgetViewMixin


class ISOWidget(
    ISOWidgetInputMixin,
    ISOWidgetRuntimeMixin,
    ISOWidgetViewMixin,
    QWidget,
):
    """DVD-/Blu-ray-ISO-Handling über MakeMKV CLI mit optionalem FFmpeg-Fallback."""

    handoff_requested = pyqtSignal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._extracted_files: list[str] = []
        self.input_list: QListWidget | None = None
        self.title_list: QListWidget | None = None
        self.output_edit: QLineEdit | None = None
        self.auto_main_title_cb: QCheckBox | None = None
        self.auto_series_disc_cb: QCheckBox | None = None
        self.ffmpeg_fallback_cb: QCheckBox | None = None
        self.handoff_cb: QCheckBox | None = None
        self.progress_bar: QProgressBar | None = None
        self.log_edit: QTextEdit | None = None
        self._btn_add_iso: QPushButton | None = None
        self._btn_add_folder: QPushButton | None = None
        self._btn_remove: QPushButton | None = None
        self._btn_clear: QPushButton | None = None
        self._btn_analyze: QPushButton | None = None
        self._btn_browse: QPushButton | None = None
        self._btn_start: QPushButton | None = None
        self._btn_abort: QPushButton | None = None
        self._worker = None
        self._scan_worker = None
        self._analyzed_input_path: str | None = None
        self._build_ui()

    def iter_shutdown_workers(self) -> tuple:
        """Explicit lifecycle hook kept on the facade for main-window shutdown discovery."""
        return ISOWidgetRuntimeMixin.iter_shutdown_workers(self)
