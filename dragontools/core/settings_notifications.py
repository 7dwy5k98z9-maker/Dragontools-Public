# -*- coding: utf-8 -*-
"""Settings contract for optional desktop notifications."""
from __future__ import annotations

from dataclasses import dataclass

from .settings_access import settings_bool

SET_KEY_NOTIFICATIONS_ENABLED = "notifications/enabled"
SET_KEY_NOTIFICATIONS_QUEUE_FINISHED = "notifications/queue_finished"
SET_KEY_NOTIFICATIONS_ERRORS = "notifications/errors"
SET_KEY_NOTIFICATIONS_FILE_FINISHED = "notifications/file_finished"

DEFAULT_NOTIFICATIONS_ENABLED = False
DEFAULT_NOTIFICATIONS_QUEUE_FINISHED = True
DEFAULT_NOTIFICATIONS_ERRORS = True
DEFAULT_NOTIFICATIONS_FILE_FINISHED = False


@dataclass(frozen=True)
class NotificationPreferences:
    enabled: bool = DEFAULT_NOTIFICATIONS_ENABLED
    queue_finished: bool = DEFAULT_NOTIFICATIONS_QUEUE_FINISHED
    errors: bool = DEFAULT_NOTIFICATIONS_ERRORS
    file_finished: bool = DEFAULT_NOTIFICATIONS_FILE_FINISHED

    @classmethod
    def from_settings(cls, settings) -> "NotificationPreferences":
        return cls(
            enabled=settings_bool(settings, SET_KEY_NOTIFICATIONS_ENABLED, DEFAULT_NOTIFICATIONS_ENABLED),
            queue_finished=settings_bool(
                settings, SET_KEY_NOTIFICATIONS_QUEUE_FINISHED, DEFAULT_NOTIFICATIONS_QUEUE_FINISHED
            ),
            errors=settings_bool(settings, SET_KEY_NOTIFICATIONS_ERRORS, DEFAULT_NOTIFICATIONS_ERRORS),
            file_finished=settings_bool(
                settings, SET_KEY_NOTIFICATIONS_FILE_FINISHED, DEFAULT_NOTIFICATIONS_FILE_FINISHED
            ),
        )


__all__ = [
    "SET_KEY_NOTIFICATIONS_ENABLED",
    "SET_KEY_NOTIFICATIONS_QUEUE_FINISHED",
    "SET_KEY_NOTIFICATIONS_ERRORS",
    "SET_KEY_NOTIFICATIONS_FILE_FINISHED",
    "DEFAULT_NOTIFICATIONS_ENABLED",
    "DEFAULT_NOTIFICATIONS_QUEUE_FINISHED",
    "DEFAULT_NOTIFICATIONS_ERRORS",
    "DEFAULT_NOTIFICATIONS_FILE_FINISHED",
    "NotificationPreferences",
]
