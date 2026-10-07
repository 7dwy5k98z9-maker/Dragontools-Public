# -*- coding: utf-8 -*-
"""Qt controller for periodic Watch-Folder scans."""
from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

from ..core.settings_watch import (
    load_processed_state, load_watch_rules, save_processed_state,
    watch_enabled, watch_scan_interval, watch_stable_seconds,
)
from ..core.watch_folder import WatchFolderCandidate, WatchFolderScanner
from ..core.path_syntax import path_compare_key
from ..core.callback_dispatch import invoke_callback, is_callback_like

from .watch_folder_intake import dispatch_watch_candidates

_LOG = logging.getLogger(__name__)


class _WatchScanThread(QThread):
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(
        self,
        scanner: WatchFolderScanner,
        rules,
        *,
        stable_seconds_override: int | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._scanner = scanner
        self._rules = list(rules)
        self._stable_seconds_override = stable_seconds_override

    def run(self) -> None:
        try:
            self.completed.emit(self._scanner.scan(
                self._rules,
                should_stop=self.isInterruptionRequested,
                stable_seconds_override=self._stable_seconds_override,
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
        self._stopped = False
        self._manual_scan_requested = False
        self._rules = []
        self._scan_generation = 0
        self._pending: dict[str, WatchFolderCandidate] = {}
        self._scanner = WatchFolderScanner(
            stable_seconds=watch_stable_seconds(settings),
            processed_state=load_processed_state(settings),
        )
        self.refresh_settings(initial=True)

    def refresh_settings(self, *, initial: bool = False) -> None:
        if self._stopped:
            return
        self._scan_generation += 1
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
        # Queued signals and singleShot callbacks survive timer.stop().
        self._stopped = True
        self._timer.stop()
        thread = self._thread
        if thread is not None and thread.isRunning():
            thread.requestInterruption()
            if not thread.wait(max(0, int(timeout_ms))):
                self._status("Watch-Folder: Scan wird noch sauber beendet …")
                return False
        self._persist_state()
        return True

    def iter_shutdown_workers(self):
        return (self._thread,) if self._thread is not None else ()

    def scan_now(self) -> bool:
        """Run an explicit Watch-Folder scan, independent of the global auto-scan toggle.

        A user-triggered scan intentionally skips the observation waiting period. The
        processed-signature state and queue de-duplication remain active, so only
        unprocessed/currently changed sources can reach the converter intake.
        """
        if self._stopped:
            return False
        self._rules = load_watch_rules(self._settings)
        self._scanner.set_stable_seconds(watch_stable_seconds(self._settings))
        if not any(rule.enabled for rule in self._rules):
            self._status("Watch-Folder: keine aktivierte Regel zum Durchsuchen vorhanden.")
            return False
        if self._thread is not None and self._thread.isRunning():
            self._manual_scan_requested = True
            self._status("Watch-Folder: laufender Scan wird beendet; manueller Scan folgt direkt danach.")
            return True
        self._start_scan(manual=True)
        return True

    def _start_scan(self, *, manual: bool = False) -> None:
        if self._stopped:
            return
        if not self._rules:
            return
        if not manual and not watch_enabled(self._settings):
            return
        if self._thread is not None and self._thread.isRunning():
            if manual:
                self._manual_scan_requested = True
            return
        thread = _WatchScanThread(
            self._scanner,
            self._rules,
            stable_seconds_override=0 if manual else None,
            parent=self,
        )
        self._thread = thread
        generation = self._scan_generation
        thread.completed.connect(
            lambda candidates, is_manual=manual, origin=thread: self._handle_candidates(
                candidates, manual=is_manual
            ) if origin is self._thread and generation == self._scan_generation else None
        )
        thread.failed.connect(
            lambda message, origin=thread: self._handle_failure(message)
            if origin is self._thread and not self._stopped else None
        )
        thread.finished.connect(lambda t=thread: self._thread_finished(t))
        if manual:
            self._status("Watch-Folder: manuelle Suche läuft …")
        thread.start()

    def _thread_finished(self, finished_thread: _WatchScanThread | None = None) -> None:
        # Bind cleanup to the thread that actually emitted ``finished``. A fast
        # previous scan may finish after a newer scan has already been assigned
        # to ``self._thread``; deleting ``self._thread`` in that case can destroy
        # the new running QThread and crash a frozen/PyInstaller executable.
        thread = finished_thread or self.sender()
        if isinstance(thread, QThread):
            thread.deleteLater()
        if thread is self._thread:
            self._thread = None
        if self._manual_scan_requested and not self._stopped:
            self._manual_scan_requested = False
            QTimer.singleShot(0, self.scan_now)

    def _handle_failure(self, message: str) -> None:
        _LOG.warning("Watch-Folder-Scan fehlgeschlagen: %s", message)
        self._status(f"Watch-Folder-Scan fehlgeschlagen: {message}")

    def _handle_candidates(self, candidates_obj, *, manual: bool = False) -> None:
        if self._stopped:
            return
        candidates = [c for c in list(candidates_obj or []) if isinstance(c, WatchFolderCandidate)]
        candidates = [
            candidate
            for candidate in candidates
            if not self._candidate_conflicts_with_pending(candidate)
        ]
        if not candidates:
            if manual:
                self._status("Watch-Folder: keine neuen Dateien gefunden.")
            return
        queued = dispatch_watch_candidates(
            candidates, pending=self._pending, enqueue=self._enqueue_callback,
            complete=self._handle_conversion_result, manual=manual, log=_LOG,
        )

        if queued:
            prefix = "Watch-Folder manuell" if manual else "Watch-Folder"
            self._status(
                f"{prefix}: {queued} Datei(en) an die Queue übergeben; "
                "als verarbeitet markiert werden sie erst nach erfolgreichem Abschluss."
            )
        elif manual:
            self._status("Watch-Folder: keine neuen Dateien außerhalb der bestehenden Queue gefunden.")

    def _candidate_conflicts_with_pending(self, candidate: WatchFolderCandidate) -> bool:
        """Keep an existing source reservation and its selected profile authoritative."""
        current = self._pending.get(path_compare_key(candidate.path))
        return bool(current is not None and (
            current.signature, current.codec, current.profile_key
        ) != (candidate.signature, candidate.codec, candidate.profile_key))

    def _handle_conversion_result(
        self, input_path: str, success: bool, output_path: str = ""
    ) -> None:
        key = path_compare_key(input_path)
        candidate = self._pending.pop(key, None)
        if candidate is None:
            return
        if success:
            # A final signature is owned by DragonTools only when the committed
            # output replaced this exact watched pathname.  Otherwise an
            # external writer may have changed the source while conversion was
            # running; acknowledge only the originally processed signature so
            # that the newer revision is scanned again.
            self._scanner.acknowledge_success(candidate, output_path=output_path)
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
