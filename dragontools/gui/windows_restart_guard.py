# -*- coding: utf-8 -*-
"""Windows-Neustartschutz fuer laufende DragonTools-Jobs."""
from __future__ import annotations
import logging

import os
import time
from typing import Any

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtWidgets import QApplication, QLabel, QMessageBox

from ..core.windows_restart_api import WindowsRestartAPI
from ..core.restart_guard_diagnostics import RestartGuardDiagnostics
from .windows_restart_native import (
    WindowsRestartEventFilter, WM_QUERYENDSESSION, WM_ENDSESSION, ENDSESSION_CRITICAL,
)

from ..core.windows_restart_policy import (
    ACTION_ALLOW,
    ACTION_ASK,
    ACTION_BLOCK,
    DEFAULT_SNOOZE_MINUTES,
    RestartGuardDecision,
    decide_windows_restart_request,
    user_initiated_shutdown_allowed,
)
from .application_shutdown import collect_shutdown_workers
from .application_worker_sources import application_worker_sources
from .shutdown_worker_state import worker_is_running


class WindowsRestartGuard(QObject):
    """Blockiert Windows-Neustarts, solange DragonTools kritische Jobs ausfuehrt."""

    def __init__(self, window: Any, *, poll_ms: int = 1000, api=None, diagnostics=None) -> None:
        super().__init__(window)
        self._window = window
        self._block_reason = ""
        self._blocked_hwnd = 0
        self._disposed = False
        self._last_error = ""
        self._last_status = None
        self._api = api
        self._diagnostics = diagnostics if diagnostics is not None else RestartGuardDiagnostics()
        self._native_filter = None
        self._status_label = None
        if os.name == "nt" and self._api is None:
            try:
                self._api = WindowsRestartAPI()
            except Exception as exc:
                self._last_error = str(exc)
        status_bar = getattr(window, "statusBar", None)
        if os.name == "nt" and callable(status_bar):
            self._status_label = QLabel("Neustartschutz: bereit", window)
            status_bar().addPermanentWidget(self._status_label)
        self._last_notice_at = 0.0
        self._snoozed_until = 0.0
        self._notice_generation = 0
        self._timer = QTimer(self)
        self._timer.setInterval(max(1000, int(poll_ms)))
        self._timer.timeout.connect(self.refresh)

        app = QApplication.instance()
        if app is not None:
            if os.name == "nt":
                try:
                    native_filter = WindowsRestartEventFilter(self)
                    app.installNativeEventFilter(native_filter)
                    self._native_filter = native_filter
                except Exception as exc:
                    self._last_error = f"Direkter Neustartschutz nicht verfügbar: {exc}"
            commit_signal = getattr(app, "commitDataRequest", None)
            if commit_signal is not None:
                commit_signal.connect(self.handle_commit_data_request)
            app.aboutToQuit.connect(self.release)
        window.destroyed.connect(self.dispose)

        self._timer.start()
        QTimer.singleShot(0, self.refresh)

    def refresh(self) -> None:
        if self._disposed:
            return
        if user_initiated_shutdown_allowed():
            self.release()
            return
        active = self._safe_active_worker_names()
        shutdown_after = self._shutdown_after_enabled()
        snoozed = self._is_snoozed()
        if not active and not snoozed:
            self.release()
            return
        decision = decide_windows_restart_request(
            active,
            shutdown_after_enabled=shutdown_after,
            interaction_allowed=False,
            snoozed=snoozed,
        )
        self._set_block_reason(decision.block_reason)

    def release(self) -> None:
        self._notice_generation += 1
        if self._api is not None:
            if self._blocked_hwnd:
                try:
                    self._api.destroy(self._blocked_hwnd)
                    self._write_event("registration_released", hwnd=self._blocked_hwnd)
                except Exception as exc:
                    self._write_event("release_failed", error=str(exc))
            try:
                self._api.restore_priority()
            except Exception as exc:
                self._write_event("priority_restore_failed", error=str(exc))
        self._blocked_hwnd = 0
        self._block_reason = ""
        if os.name == "nt" and (self._api is None or self._native_filter is None) and not self._disposed:
            self._set_status("eingeschränkt", self._last_error or "Windows-Neustartschutz konnte nicht vollständig eingerichtet werden.")
        else:
            self._set_status("bereit", "Aktiviert sich bei laufenden DragonTools-Aufträgen.")

    def handle_commit_data_request(self, manager: Any) -> None:
        decision = decide_windows_restart_request(
            self._safe_active_worker_names(),
            shutdown_after_enabled=self._shutdown_after_enabled(),
            interaction_allowed=self._manager_allows_interaction(manager),
            snoozed=self._is_snoozed(),
            user_shutdown_allowed=user_initiated_shutdown_allowed(),
        )

        if decision.action == ACTION_ALLOW:
            self.release()
            return
        if decision.action == ACTION_ASK:
            answer = self._ask_user(decision)
            if answer == ACTION_ALLOW and not self._safe_active_worker_names():
                self._snoozed_until = 0.0
                self.release()
                return
            if answer == "snooze":
                self._snoozed_until = time.monotonic() + DEFAULT_SNOOZE_MINUTES * 60
                decision = decide_windows_restart_request(
                    (),
                    shutdown_after_enabled=False,
                    interaction_allowed=False,
                    snoozed=True,
                )
            else:
                decision = RestartGuardDecision(
                    ACTION_BLOCK,
                    "Windows-Neustart blockiert",
                    "Der Windows-Neustart wurde auf deine Entscheidung hin blockiert.",
                    "DragonTools blockiert den Windows-Neustart nach Benutzerentscheidung.",
                )

        cancelled = self._cancel_manager(manager)
        self._write_event("qt_session_query", action=decision.action, cancel_called=cancelled,
                          workers=list(decision.active_workers))
        if decision.action == ACTION_BLOCK:
            self._set_block_reason(decision.block_reason)
            if cancelled:
                self._show_block_notice(decision)
            else:
                self._set_status("eingeschränkt", "Windows-Neustart konnte über Qt nicht abgelehnt werden; siehe Protokoll.")

    def _active_worker_names(self) -> tuple[str, ...]:
        names = list(
            _worker_display_name(worker)
            for worker in collect_shutdown_workers(application_worker_sources(self._window))
            if worker_is_running(worker)
        )
        # The synchronous reservation also covers preflight and the brief
        # conversion-to-move handoff before QThread.isRunning() becomes true.
        widgets = getattr(self._window, "_tab_widgets", {}) or {}
        for widget in (widgets.values() if hasattr(widgets, "values") else widgets):
            state = getattr(widget, "_state", None)
            if state is not None and (getattr(state, "start_reserved", False)
                                      or getattr(state, "finalization_in_progress", False)):
                names.append("DragonTools-Auftrag wird gestartet/abgeschlossen")
        return tuple(dict.fromkeys(names))

    def _safe_active_worker_names(self) -> tuple[str, ...]:
        try:
            return self._active_worker_names()
        except Exception as exc:
            self._write_event("worker_discovery_failed", error=str(exc))
            return ("Auftragsstatus nicht sicher ermittelbar",)

    def _shutdown_after_enabled(self) -> bool:
        widgets = getattr(self._window, "_tab_widgets", {}) or {}
        values = widgets.values() if hasattr(widgets, "values") else widgets
        for widget in values:
            for owner in (widget, getattr(widget, "w", None), getattr(widget, "ui", None)):
                checkbox = getattr(owner, "shut_cb", None)
                if checkbox is None:
                    continue
                try:
                    if bool(checkbox.isChecked()):
                        return True
                except Exception:
                    continue
        return False

    def _is_snoozed(self) -> bool:
        return time.monotonic() < self._snoozed_until

    def _manager_allows_interaction(self, manager: Any) -> bool:
        for name in ("allowsInteraction", "allowsErrorInteraction"):
            method = getattr(manager, name, None)
            if callable(method):
                try:
                    if bool(method()):
                        return True
                except Exception:
                    continue
        return False

    def _ask_user(self, decision: RestartGuardDecision) -> str:
        box = QMessageBox(self._window)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(decision.title)
        box.setText(decision.message)
        box.setInformativeText("Möchtest du den Neustart zulassen?")
        allow = box.addButton("Zulassen", QMessageBox.ButtonRole.AcceptRole)
        block = box.addButton("Nein, blockieren", QMessageBox.ButtonRole.RejectRole)
        snooze = box.addButton(
            f"In {DEFAULT_SNOOZE_MINUTES} Minuten erneut fragen",
            QMessageBox.ButtonRole.ActionRole,
        )
        box.setDefaultButton(block)
        box.exec()
        clicked = box.clickedButton()
        if clicked is allow:
            return ACTION_ALLOW
        if clicked is snooze:
            return "snooze"
        return ACTION_BLOCK

    def _cancel_manager(self, manager: Any) -> bool:
        cancel = getattr(manager, "cancel", None)
        if callable(cancel):
            try:
                cancel()
                return True
            except Exception as exc:
                self._write_event("qt_cancel_failed", error=str(exc))
        else:
            self._write_event("qt_cancel_failed", error="Qt bietet keine Abbruchfunktion")
        return False

    def _show_block_notice(self, decision: RestartGuardDecision) -> None:
        now = time.monotonic()
        if now - self._last_notice_at < 30:
            return
        self._last_notice_at = now

        generation = self._notice_generation

        def _show() -> None:
            if generation != self._notice_generation:
                return
            status_bar = getattr(self._window, "statusBar", None)
            if callable(status_bar):
                status_bar().showMessage("Windows-Neustartanforderung abgelehnt: DragonTools arbeitet noch.", 15000)

        QTimer.singleShot(0, _show)

    def _set_block_reason(self, reason: str) -> None:
        reason = str(reason or "").strip()
        if os.name != "nt" or not reason:
            self.release()
            return
        hwnd = self._hwnd()
        if not hwnd:
            self._registration_failed("Kein gültiges DragonTools-Fenster verfügbar")
            return
        if self._api is None:
            self._registration_failed(self._last_error or "Windows-Neustartschutz nicht verfügbar")
            return
        try:
            changed = self._blocked_hwnd != hwnd or self._block_reason != reason
            if not changed:
                try:
                    changed = self._api.query(hwnd) != reason
                except OSError:
                    changed = True
            if changed:
                if self._blocked_hwnd and self._blocked_hwnd != hwnd:
                    try:
                        self._api.destroy(self._blocked_hwnd)
                    except Exception as exc:
                        # Qt may already have destroyed the old HWND. That
                        # must not prevent protection of its replacement.
                        self._write_event("old_window_release_failed", hwnd=self._blocked_hwnd, error=str(exc))
                    self._blocked_hwnd = 0
                self._api.prioritize()
                # Retain the HWND even if the verification query fails after
                # Create succeeded, so idle/exit still cleans up the registration.
                self._blocked_hwnd = hwnd
                self._block_reason = self._api.create(hwnd, reason)
                self._write_event("registration_verified", hwnd=hwnd, reason=reason,
                                  native_filter=self._native_filter is not None)
            if self._native_filter is None:
                self._registration_failed("Direkter Neustartschutz nicht verfügbar; nur Qt-Rückfallebene aktiv",
                                          preserve_registration=True)
                return
            self._last_error = ""
            self._set_status("aktiv", "Windows-Registrierung geprüft; Neustartanforderungen werden direkt abgewiesen.\n"
                             "Erzwungenes Ausschalten kann Windows trotzdem durchsetzen.")
        except Exception as exc:
            self._registration_failed(str(exc))

    def _registration_failed(self, detail: str, *, preserve_registration: bool = False) -> None:
        if detail != self._last_error or self._last_status is None:
            self._write_event("registration_failed", error=detail, hwnd=self._hwnd())
        self._last_error = detail
        if not preserve_registration:
            self._block_reason = ""
        self._set_status("eingeschränkt", "Neustartschutz konnte nicht vollständig bestätigt werden.\n" + detail)

    def _write_event(self, event: str, **details) -> None:
        try:
            self._diagnostics.record(event, **details)
        except Exception:
            logging.getLogger(__name__).exception("Neustartschutz-Diagnose fehlgeschlagen")

    def _set_status(self, state: str, detail: str) -> None:
        if self._disposed:
            return
        log_error = getattr(self._diagnostics, "error", "")
        if log_error:
            state += " (Protokollfehler)"
            detail += "\nProtokoll nicht verfügbar: " + str(log_error)
        self._last_status = state, detail
        if self._status_label is not None:
            self._status_label.setText("Neustartschutz: " + state)
            self._status_label.setToolTip(detail + "\nProtokoll: " + str(getattr(self._diagnostics, "path", "")))
            color = "#26703b" if state == "aktiv" else ("#a65a00" if "eingeschränkt" in state or log_error else "")
            self._status_label.setStyleSheet(f"color: {color};" if color else "")

    def handle_native_message(self, message: int, wparam: int, flags: int) -> tuple[bool, int]:
        if self._disposed or message not in {WM_QUERYENDSESSION, WM_ENDSESSION}:
            return False, 0
        active = self._safe_active_worker_names()
        if message == WM_ENDSESSION:
            self._write_event("native_session_end", ending=bool(wparam), flags=int(flags),
                              critical=bool(flags & ENDSESSION_CRITICAL), workers=list(active))
            return False, 0
        if user_initiated_shutdown_allowed() or (not active and not self._is_snoozed()):
            self._write_event("native_query_deferred", flags=int(flags), workers=list(active))
            if user_initiated_shutdown_allowed():
                self.release()
            return False, 0
        decision = decide_windows_restart_request(active, shutdown_after_enabled=self._shutdown_after_enabled(),
                                                  interaction_allowed=False, snoozed=self._is_snoozed())
        self._set_block_reason(decision.block_reason)
        self._write_event("native_query_rejected", flags=int(flags), critical=bool(flags & ENDSESSION_CRITICAL),
                          workers=list(active), registration_verified=bool(self._block_reason))
        self._show_block_notice(decision)
        # FALSE is the Win32 veto. Returning True here tells Qt that the native
        # message is handled; it must not start closing/aborting worker windows.
        return True, 0

    def native_filter_error(self, exc) -> None:
        self._write_event("native_filter_failed", error=str(exc))
        self._set_status("eingeschränkt", "Direkte Windows-Neustartprüfung fehlgeschlagen: " + str(exc))

    def dispose(self, *_args) -> None:
        if self._disposed:
            return
        self._disposed = True
        self._timer.stop()
        app = QApplication.instance()
        if app is not None and self._native_filter is not None:
            app.removeNativeEventFilter(self._native_filter)
            self._native_filter = None
        self.release()

    def _hwnd(self) -> int:
        try:
            return int(self._window.winId())
        except Exception:
            return 0


def _worker_display_name(worker: Any) -> str:
    try:
        name = worker.objectName()
        if name:
            return str(name)
    except Exception:
        logging.getLogger(__name__).debug("Unterdrückte Best-Effort-Ausnahme in _worker_display_name.", exc_info=True)
    return worker.__class__.__name__


def install_windows_restart_guard(window: Any) -> WindowsRestartGuard:
    existing = getattr(window, "_windows_restart_guard", None)
    if isinstance(existing, WindowsRestartGuard):
        return existing
    guard = WindowsRestartGuard(window)
    setattr(window, "_windows_restart_guard", guard)
    return guard


__all__ = ["WindowsRestartGuard", "install_windows_restart_guard"]
