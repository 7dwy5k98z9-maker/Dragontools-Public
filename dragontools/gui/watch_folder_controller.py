# -*- coding: utf-8 -*-
"""Qt controller for periodic Watch-Folder scans."""
from __future__ import annotations

import logging
from collections import defaultdict

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

from ..core.settings_watch import (
    load_processed_state, load_watch_rules, save_processed_state,
    watch_enabled, watch_scan_interval, watch_stable_seconds,
)
from ..core.watch_folder import WatchFolderCandidate, WatchFolderScanner
from ..core.path_syntax import path_compare_key
from ..core.callback_dispatch import invoke_callback, is_callback_like

_LOG = logging.getLogger(__name__)


class _WatchScanThread(QThread):
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, scanner: WatchFolderScanner, rules, parent=None) -> None:
        super().__init__(parent)
        self._scanner = scanner
        self._rules = list(rules)

    def run(self) -> None:
        try:
            self.completed.emit(self._scanner.scan(
                self._rules, should_stop=self.isInterruptionRequested
            ))
        except Exception as exc:
            _LOG.exception("Watch-Folder-Scan fehlgeschlagen")
            self.failed.emit(str(exc))


class WatchFolderController(QObject):
    """Owns timer, scanner state and dispatch into the existing converter queues."""

    def __init__(self, *, settings, enqueue_callback, status_callback=None, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._enqueue_callback = enqueue_callback
        self._status_callback = status_callback
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._start_scan)
        self._thread: _WatchScanThread | None = None
        self._rules = []
        self._pending: dict[str, WatchFolderCandidate] = {}
        self._scanner = WatchFolderScanner(
            stable_seconds=watch_stable_seconds(settings),
            processed_state=load_processed_state(settings),
        )
        self.refresh_settings(initial=True)

    def refresh_settings(self, *, initial: bool = False) -> None:
        self._rules = load_watch_rules(self._settings)
        self._scanner.set_stable_seconds(watch_stable_seconds(self._settings))
        interval_ms = watch_scan_interval(self._settings) * 1000
        self._timer.setInterval(interval_ms)
        enabled = watch_enabled(self._settings) and any(rule.enabled for rule in self._rules)
        if enabled:
            if not self._timer.isActive():
                self._timer.start()
            QTimer.singleShot(250 if initial else 0, self._start_scan)
        else:
            self._timer.stop()

    def stop(self, *, timeout_ms: int = 8000) -> bool:
        self._timer.stop()
        thread = self._thread
        if thread is not None and thread.isRunning():
            thread.requestInterruption()
            if not thread.wait(max(0, int(timeout_ms))):
                self._status("Watch-Folder: Scan wird noch sauber beendet …")
                return False
        self._persist_state()
        return True

    def _start_scan(self) -> None:
        if not watch_enabled(self._settings) or not self._rules:
            return
        if self._thread is not None and self._thread.isRunning():
            return
        thread = _WatchScanThread(self._scanner, self._rules, self)
        self._thread = thread
        thread.completed.connect(self._handle_candidates)
        thread.failed.connect(self._handle_failure)
        thread.finished.connect(self._thread_finished)
        thread.start()

    def _thread_finished(self) -> None:
        thread = self._thread
        if thread is not None:
            thread.deleteLater()
        self._thread = None

    def _handle_failure(self, message: str) -> None:
        _LOG.warning("Watch-Folder-Scan fehlgeschlagen: %s", message)
        self._status(f"Watch-Folder-Scan fehlgeschlagen: {message}")

    def _handle_candidates(self, candidates_obj) -> None:
        candidates = [c for c in list(candidates_obj or []) if isinstance(c, WatchFolderCandidate)]
        candidates = [
            candidate
            for candidate in candidates
            if not self._candidate_conflicts_with_pending(candidate)
        ]
        if not candidates:
            return
        grouped: dict[tuple[str, str, bool], list[WatchFolderCandidate]] = defaultdict(list)
        for candidate in candidates:
            grouped[(candidate.codec, candidate.profile_key, candidate.auto_start)].append(candidate)

        queued = 0
        for (codec, profile_key, auto_start), group in grouped.items():
            for candidate in group:
                self._pending[path_compare_key(candidate.path)] = candidate
            paths = [candidate.path for candidate in group]
            try:
                handled = set(self._enqueue_callback(
                    codec=codec,
                    paths=paths,
                    profile_key=profile_key,
                    auto_start=auto_start,
                    completion_callback=self._handle_conversion_result,
                ) or [])
            except Exception:
                _LOG.exception("Watch-Folder-Übergabe an Converter fehlgeschlagen")
                handled = set()

            for candidate in group:
                key = path_compare_key(candidate.path)
                if candidate.path in handled:
                    queued += 1
                else:
                    current = self._pending.get(key)
                    if current == candidate:
                        self._pending.pop(key, None)

        if queued:
            self._status(
                f"Watch-Folder: {queued} Datei(en) an die Queue übergeben; "
                "als verarbeitet markiert werden sie erst nach erfolgreichem Abschluss."
            )

    def _candidate_conflicts_with_pending(self, candidate: WatchFolderCandidate) -> bool:
        """Defer a changed source while its previous signature is still running.

        The same signature is intentionally offered to the queue again on every
        scan. Queue de-duplication makes that cheap and it lets a manually removed
        watch item be re-enqueued instead of remaining stuck in pending state.
        """
        current = self._pending.get(path_compare_key(candidate.path))
        return bool(current is not None and current.signature != candidate.signature)

    def _handle_conversion_result(self, input_path: str, success: bool) -> None:
        key = path_compare_key(input_path)
        candidate = self._pending.pop(key, None)
        if candidate is None:
            return
        if success:
            # The job may have replaced the watched source in-place.  Persist
            # the final output signature, not the pre-conversion signature, or
            # the Watch-Folder would enqueue DragonTools' own result again.
            self._scanner.acknowledge_current(candidate)
            self._persist_state()
            self._status(f"Watch-Folder: erfolgreich verarbeitet: {input_path}")
        else:
            self._status(
                f"Watch-Folder: Verarbeitung nicht erfolgreich; Datei bleibt für einen erneuten Versuch offen: {input_path}"
            )

    def _persist_state(self) -> None:
        save_processed_state(self._settings, self._scanner.processed_state())
        try:
            self._settings.sync()
        except Exception:
            logging.getLogger(__name__).debug("Unterdrückte Best-Effort-Ausnahme in _persist_state.", exc_info=True)

    def _status(self, text: str) -> None:
        callback = self._status_callback
        if is_callback_like(callback):
            try:
                invoke_callback(callback, text)
            except Exception:
                _LOG.debug("Watch-Folder-Status konnte nicht angezeigt werden", exc_info=True)


__all__ = ["WatchFolderController"]
