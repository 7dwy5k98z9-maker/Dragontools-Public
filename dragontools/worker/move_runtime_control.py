# -*- coding: utf-8 -*-
"""Qt-unabhängige Laufzeitsteuerung für ``MoveThread``.

Das Mixin besitzt keinen QThread-Lifecycle. Es kapselt ausschließlich
Benutzerentscheidungen, Pause/Resume/Abort und geplante Zielpfade.
"""
from __future__ import annotations

import threading
import uuid


class MoveRuntimeControlMixin:
    """Steuert Interaktion und Laufzustand eines Move-Workers."""

    def provide_decision(self, rid, resp):
        self._responses[rid] = resp
        ev = self._events.get(rid)
        if ev:
            ev.set()

    def add_planned_target(self, path: str, target) -> None:
        with self._planned_targets_lock:
            if path not in self.planned_targets:
                self.planned_targets[path] = target

    def request_abort(self, mode: str = "sofort") -> None:
        self.abort_requested = True
        self.abort_type = mode
        if self._paused:
            self.resume()
        self._log(f"Abort für Verschieben angefordert ({mode}).", "warn")

    def pause(self) -> None:
        self._paused = True
        self._pause_ev.clear()
        self._log("⏸️ Verschieben pausiert.", "info")

    def resume(self) -> None:
        self._paused = False
        self._pause_ev.set()
        self._log("▶️ Verschieben fortgesetzt.", "info")

    def _wait(self) -> None:
        if getattr(self, "_paused", False):
            self._pause_ev.wait()

    def _ask(self, payload, timeout: float | None = None) -> dict:
        rid = str(uuid.uuid4())
        ev = threading.Event()
        self._events[rid] = ev
        self.request_user.emit(rid, payload)
        try:
            if timeout is None:
                while not ev.wait(timeout=0.5):
                    if self.abort_requested:
                        return {"abort": True}
            else:
                answered = ev.wait(timeout=timeout)
                if not answered:
                    self._log(
                        f"Timeout bei Benutzer-Abfrage (Typ: {payload.get('type', '?')}) - Abbruch.",
                        "warn",
                    )
            return self._responses.pop(rid, {"abort": True})
        finally:
            self._events.pop(rid, None)

    def _log(self, msg, level="info"):
        lv = (level or "info").lower()
        getattr(self._logger, lv, self._logger.info)(msg)
