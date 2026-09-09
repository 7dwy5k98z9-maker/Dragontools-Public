# -*- coding: utf-8 -*-
"""Qt-unabhaengige Entscheidung fuer Windows-Neustartanforderungen."""
from __future__ import annotations

from dataclasses import dataclass
import time


ACTION_ALLOW = "allow"
ACTION_ASK = "ask"
ACTION_BLOCK = "block"
DEFAULT_SNOOZE_MINUTES = 15

_USER_SHUTDOWN_ALLOWED_UNTIL = 0.0


@dataclass(frozen=True)
class RestartGuardDecision:
    action: str
    title: str
    message: str
    block_reason: str
    active_workers: tuple[str, ...] = ()
    shutdown_after_enabled: bool = False


def allow_user_initiated_shutdown(*, seconds: int = 180) -> None:
    """Gibt den naechsten System-Shutdown frei, wenn DragonTools ihn selbst ausloest."""
    global _USER_SHUTDOWN_ALLOWED_UNTIL
    _USER_SHUTDOWN_ALLOWED_UNTIL = time.monotonic() + max(1, int(seconds or 1))


def clear_user_initiated_shutdown() -> None:
    global _USER_SHUTDOWN_ALLOWED_UNTIL
    _USER_SHUTDOWN_ALLOWED_UNTIL = 0.0


def user_initiated_shutdown_allowed() -> bool:
    return time.monotonic() <= _USER_SHUTDOWN_ALLOWED_UNTIL


def decide_windows_restart_request(
    active_workers: tuple[str, ...] | list[str],
    *,
    shutdown_after_enabled: bool,
    interaction_allowed: bool,
    snoozed: bool = False,
    user_shutdown_allowed: bool = False,
) -> RestartGuardDecision:
    workers = tuple(str(name) for name in active_workers if str(name).strip())
    if user_shutdown_allowed:
        return RestartGuardDecision(
            ACTION_ALLOW,
            "DragonTools-Herunterfahren",
            "Der System-Shutdown wurde von DragonTools selbst gestartet.",
            "",
            workers,
            shutdown_after_enabled,
        )

    if workers:
        if shutdown_after_enabled:
            message = (
                "Windows hat einen Neustart angefragt. DragonTools verarbeitet gerade "
                "Dateien und hat Herunterfahren nach Abschluss aktiv. Der Windows-Neustart "
                "wird bis zum Abschluss blockiert; danach startet DragonTools den "
                "konfigurierten Shutdown selbst."
            )
            reason = "DragonTools verarbeitet Dateien und fährt danach herunter."
        else:
            message = (
                "Windows hat einen Neustart angefragt. DragonTools verarbeitet gerade "
                "Dateien. Der Neustart wird blockiert, damit keine laufende Konvertierung "
                "oder Dateioperation beschädigt wird."
            )
            reason = "DragonTools verarbeitet Dateien. Neustart nach Abschluss erneut starten."
        return RestartGuardDecision(
            ACTION_BLOCK,
            "Windows-Neustart blockiert",
            message,
            reason,
            workers,
            shutdown_after_enabled,
        )

    if snoozed:
        return RestartGuardDecision(
            ACTION_BLOCK,
            "Windows-Neustart verschoben",
            "Der Windows-Neustart wurde in DragonTools vorübergehend verschoben.",
            "Windows-Neustart in DragonTools vorübergehend verschoben.",
            workers,
            shutdown_after_enabled,
        )

    if interaction_allowed:
        return RestartGuardDecision(
            ACTION_ASK,
            "Windows-Neustart angefragt",
            "Windows möchte den Computer neu starten. In DragonTools läuft aktuell kein Job.",
            "",
            workers,
            shutdown_after_enabled,
        )

    return RestartGuardDecision(
        ACTION_BLOCK,
        "Windows-Neustart blockiert",
        "Windows möchte den Computer neu starten, aber DragonTools konnte keinen Dialog anzeigen.",
        "DragonTools wartet auf eine bewusste Neustartentscheidung.",
        workers,
        shutdown_after_enabled,
    )


__all__ = [
    "ACTION_ALLOW",
    "ACTION_ASK",
    "ACTION_BLOCK",
    "DEFAULT_SNOOZE_MINUTES",
    "RestartGuardDecision",
    "allow_user_initiated_shutdown",
    "clear_user_initiated_shutdown",
    "decide_windows_restart_request",
    "user_initiated_shutdown_allowed",
]
