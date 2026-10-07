"""A dialog-owned Qt receiver mirrors one log without surviving its widgets."""
from PyQt6.QtCore import QObject, Qt, pyqtSlot
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QTextEdit, QVBoxLayout

from .qt_receiver_state import receiver_is_alive
from .ui_helpers import install_persistent_window_geometry


class LogMirror(QObject):
    def __init__(self, source, view, parent):
        super().__init__(parent)
        self._source = source
        self._view = view
        self._previous = ""
        source.textChanged.connect(self.sync)
        source.destroyed.connect(self.source_destroyed)
        self.sync()

    @pyqtSlot()
    def sync(self):
        source = self._source
        if source is None or not receiver_is_alive(source) or not receiver_is_alive(self._view):
            return
        current = source.toPlainText()
        if current == self._previous:
            return
        if current.startswith(self._previous):
            cursor = self._view.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self._view.setTextCursor(cursor)
            self._view.insertPlainText(current[len(self._previous):])
        else:
            self._view.setPlainText(current)
        self._previous = current
        bar = self._view.verticalScrollBar()
        bar.setValue(bar.maximum())

    @pyqtSlot()
    def source_destroyed(self):
        self._source = None

    @pyqtSlot(int)
    def detach(self, _result=0):
        source, self._source = self._source, None
        if source is not None and receiver_is_alive(source):
            source.textChanged.disconnect(self.sync)
            source.destroyed.disconnect(self.source_destroyed)


def open_log_zoom_window(parent, source):
    dialog = QDialog(parent)
    dialog.setWindowTitle("📋 Logging-Fenster")
    dialog.setMinimumSize(900, 600)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    install_persistent_window_geometry(dialog, "log_zoom_window")
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(8, 8, 8, 8)
    view = QTextEdit(dialog)
    view.setReadOnly(True)
    view.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
    view.setStyleSheet("font-family: Consolas, monospace; font-size: 11px;")
    layout.addWidget(view)
    if source is not None and receiver_is_alive(source):
        dialog._log_mirror = LogMirror(source, view, dialog)
        dialog.finished.connect(dialog._log_mirror.detach)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=dialog)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    dialog.show()
    return dialog
