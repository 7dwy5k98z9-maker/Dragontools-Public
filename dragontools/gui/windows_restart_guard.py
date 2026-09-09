# -*- coding: utf-8 -*-
"""Windows-Neustartschutz fuer laufende DragonTools-Jobs."""
from __future__ import annotations

import ctypes
import os
import time
from typing import Any

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

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


class WindowsRestartGuard(QObject):
    """Blockiert Windows-Neustarts, solange DragonTools kritische Jobs ausfuehrt."""

    def __init__(self, window: Any, *, poll_ms: int = 5000) -> None:
        super().__init__(window)
        self._window = window
        self._block_reason = ""
        self._last_notice_at = 0.0
        self._snoozed_until = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(max(1000, int(poll_ms)))
        self._timer.timeout.connect(self.refresh)

        app = QApplication.instance()
        if app is not None:
            commit_signal = getattr(app, "commitDataRequest", None)
            if commit_signal is not None:
                commit_signal.connect(self.handle_commit_data_request)
            app.aboutToQuit.connect(self.release)

        self._timer.start()
        QTimer.singleShot(0, self.refresh)

    def refresh(self) -> None:
        if user_initiated_shutdown_allowed():
            self.release()
            return
        active = self._active_worker_names()
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
        if os.name != "nt" or not self._block_reason:
            self._block_reason = ""
            return
        hwnd = self._hwnd()
        if hwnd:
            try:
                ctypes.windll.user32.ShutdownBlockReasonDestroy(hwnd)
            except Exception:
                pass
        self._block_reason = ""

    def handle_commit_data_request(self, manager: Any) -> None:
        decision = decide_windows_restart_request(
            self._active_worker_names(),
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
            if answer == ACTION_ALLOW:
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

        self._cancel_manager(manager)
        if decision.action == ACTION_BLOCK:
            self._set_block_reason(decision.block_reason)
            self._show_block_notice(decision)

    def _active_worker_names(self) -> tuple[str, ...]:
        widgets = getattr(self._window, "_tab_widgets", {}) or {}
        values = widgets.values() if hasattr(widgets, "values") else widgets
        names: list[str] = []
        for worker in collect_shutdown_workers(values):
            try:
                if not bool(worker.isRunning()):
                    continue
            except Exception:
                continue
            names.append(_worker_display_name(worker))
        return tuple(names)

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

    def _cancel_manager(self, manager: Any) -> None:
        cancel = getattr(manager, "cancel", None)
        if callable(cancel):
            try:
                cancel()
            except Exception:
                pass

    def _show_block_notice(self, decision: RestartGuardDecision) -> None:
        now = time.monotonic()
        if now - self._last_notice_at < 30:
            return
        self._last_notice_at = now

        def _show() -> None:
            QMessageBox.information(self._window, decision.title, decision.message)

        QTimer.singleShot(0, _show)

    def _set_block_reason(self, reason: str) -> None:
        reason = str(reason or "").strip()
        if os.name != "nt" or not reason:
            self.release()
            return
        if self._block_reason == reason:
            return
        hwnd = self._hwnd()
        if not hwnd:
            return
        self.release()
        try:
            ok = bool(ctypes.windll.user32.ShutdownBlockReasonCreate(hwnd, reason))
        except Exception:
            ok = False
        if ok:
            self._block_reason = reason

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
        pass
    return worker.__class__.__name__


def install_windows_restart_guard(window: Any) -> WindowsRestartGuard:
    guard = WindowsRestartGuard(window)
    setattr(window, "_windows_restart_guard", guard)
    return guard


__all__ = ["WindowsRestartGuard", "install_windows_restart_guard"]
