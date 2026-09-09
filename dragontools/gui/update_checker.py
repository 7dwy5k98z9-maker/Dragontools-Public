# -*- coding: utf-8 -*-
"""Nicht blockierende GitHub-Release-Abfrage für die Qt-Oberfläche."""
from __future__ import annotations

from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from ..core.update_check import UPDATE_API_URL, UpdateCheckResult, parse_release_response
from ..core.version import APP_VERSION


class GitHubUpdateChecker(QObject):
    finished = pyqtSignal(object)

    def __init__(self, parent: QObject | None = None, *, timeout_ms: int = 7000) -> None:
        super().__init__(parent)
        self._manager = QNetworkAccessManager(self)
        self._timeout_ms = timeout_ms
        self._reply: QNetworkReply | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._abort_for_timeout)
        self._timed_out = False

    @property
    def running(self) -> bool:
        return self._reply is not None

    def start(self) -> bool:
        if self.running:
            return False
        self._timed_out = False
        request = QNetworkRequest(QUrl(UPDATE_API_URL))
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setRawHeader(b"X-GitHub-Api-Version", b"2022-11-28")
        request.setRawHeader(b"User-Agent", f"DragonTools/{APP_VERSION}".encode("ascii"))
        self._reply = self._manager.get(request)
        self._reply.finished.connect(self._on_finished)
        self._timer.start(self._timeout_ms)
        return True

    def _abort_for_timeout(self) -> None:
        if self._reply is not None:
            self._timed_out = True
            self._reply.abort()

    def _on_finished(self) -> None:
        reply = self._reply
        self._reply = None
        self._timer.stop()
        if reply is None:
            return

        if self._timed_out:
            result = UpdateCheckResult(ok=False, error="Zeitüberschreitung bei der Updateprüfung.")
        elif reply.error() != QNetworkReply.NetworkError.NoError:
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            if status == 404:
                message = "Die öffentliche Updatequelle ist noch nicht verfügbar."
            else:
                message = reply.errorString() or "Die Updatequelle konnte nicht erreicht werden."
            result = UpdateCheckResult(ok=False, error=message)
        else:
            result = parse_release_response(bytes(reply.readAll()), APP_VERSION)

        reply.deleteLater()
        self.finished.emit(result)

