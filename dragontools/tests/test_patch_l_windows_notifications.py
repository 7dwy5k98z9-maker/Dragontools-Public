from __future__ import annotations

from pathlib import Path

from dragontools.core.conversion_notifications import ConversionNotificationService
from dragontools.core.settings_notifications import (
    DEFAULT_NOTIFICATIONS_ENABLED,
    NotificationPreferences,
    SET_KEY_NOTIFICATIONS_ENABLED,
    SET_KEY_NOTIFICATIONS_ERRORS,
    SET_KEY_NOTIFICATIONS_FILE_FINISHED,
    SET_KEY_NOTIFICATIONS_QUEUE_FINISHED,
)


class FakeSettings:
    def __init__(self, values: dict | None = None) -> None:
        self.values = dict(values or {})

    def value(self, key, default=None, type=None):  # noqa: A002 - QSettings-compatible test double
        value = self.values.get(key, default)
        if type is bool:
            return bool(value)
        return value


def _enabled_settings(**overrides) -> FakeSettings:
    values = {
        SET_KEY_NOTIFICATIONS_ENABLED: True,
        SET_KEY_NOTIFICATIONS_QUEUE_FINISHED: True,
        SET_KEY_NOTIFICATIONS_ERRORS: True,
        SET_KEY_NOTIFICATIONS_FILE_FINISHED: False,
    }
    values.update(overrides)
    return FakeSettings(values)


def test_notifications_are_opt_in_by_default() -> None:
    prefs = NotificationPreferences.from_settings(FakeSettings())
    assert prefs.enabled is DEFAULT_NOTIFICATIONS_ENABLED is False
    assert prefs.queue_finished is True
    assert prefs.errors is True
    assert prefs.file_finished is False


def test_successful_file_notification_is_separately_optional() -> None:
    emitted: list[tuple[str, str, str]] = []
    settings = _enabled_settings()
    service = ConversionNotificationService(settings=settings, emit=lambda *args: emitted.append(args) or True)

    service.on_file_result(r"D:\Input\Film.mkv", "✅")
    assert emitted == []

    settings.values[SET_KEY_NOTIFICATIONS_FILE_FINISHED] = True
    service.on_file_result(r"D:\Input\Film.mkv", "✅")
    assert emitted == [("Datei abgeschlossen", "Film.mkv", "info")]


def test_file_error_is_reported_immediately_when_enabled() -> None:
    emitted: list[tuple[str, str, str]] = []
    service = ConversionNotificationService(
        settings=_enabled_settings(), emit=lambda *args: emitted.append(args) or True
    )
    service.on_file_result("episode.mkv", "❌", "Encoder ist fehlgeschlagen")
    assert emitted == [
        ("Fehler bei Datei", "episode.mkv\nEncoder ist fehlgeschlagen", "error")
    ]


def test_skipped_file_does_not_generate_error_notification() -> None:
    emitted: list[tuple[str, str, str]] = []
    service = ConversionNotificationService(
        settings=_enabled_settings(), emit=lambda *args: emitted.append(args) or True
    )
    service.on_file_result("episode.mkv", "⏭️", "bewusst übersprungen")
    assert emitted == []


def test_queue_notification_contains_result_and_move_counts() -> None:
    emitted: list[tuple[str, str, str]] = []
    service = ConversionNotificationService(
        settings=_enabled_settings( **{SET_KEY_NOTIFICATIONS_ERRORS: False}),
        emit=lambda *args: emitted.append(args) or True,
    )
    service.on_run_finished({"ok": 7, "errors": 1, "skipped": 2, "move_ok": 6, "move_errors": 0})
    assert emitted == [(
        "Queue abgeschlossen",
        "7 erfolgreich · 1 Fehler · 2 übersprungen · Verschieben: 6 OK / 0 Fehler",
        "warning",
    )]


def test_move_errors_get_error_notification_and_queue_summary() -> None:
    emitted: list[tuple[str, str, str]] = []
    service = ConversionNotificationService(
        settings=_enabled_settings(), emit=lambda *args: emitted.append(args) or True
    )
    service.on_run_finished({"ok": 4, "errors": 0, "skipped": 0, "move_ok": 3, "move_errors": 1})
    assert emitted[0] == ("Verschieben mit Fehlern", "1 Fehler, 3 erfolgreich verschoben.", "error")
    assert emitted[1][0] == "Queue abgeschlossen"
    assert emitted[1][2] == "warning"


def test_aborted_run_never_claims_queue_completed() -> None:
    emitted: list[tuple[str, str, str]] = []
    service = ConversionNotificationService(
        settings=_enabled_settings(), emit=lambda *args: emitted.append(args) or True
    )
    service.on_run_finished({"ok": 1, "errors": 0}, aborted=True)
    assert emitted == []


def test_notification_backend_failure_is_best_effort() -> None:
    log_rows: list[tuple[str, str]] = []

    def broken_emit(*_args):
        raise RuntimeError("tray unavailable")

    service = ConversionNotificationService(
        settings=_enabled_settings(),
        emit=broken_emit,
        log=lambda message, level="info": log_rows.append((message, level)),
    )
    service.on_file_result("film.mkv", "❌", "kaputt")
    assert len(log_rows) == 1
    assert "konnte nicht angezeigt werden" in log_rows[0][0]
    assert log_rows[0][1] == "warn"


def test_patch_l_is_wired_to_result_and_windows_backend_sources() -> None:
    root = Path(__file__).resolve().parents[1]
    file_events = (root / "gui" / "conversion_result_file_events.py").read_text(encoding="utf-8")
    finalizer = (root / "gui" / "conversion_run_finalizer.py").read_text(encoding="utf-8")
    backend = (root / "gui" / "windows_notification_backend.py").read_text(encoding="utf-8")
    settings = (root / "gui" / "settings_sections" / "notifications.py").read_text(encoding="utf-8")

    assert "notifications.on_file_result" in file_events
    assert "notifications.on_run_finished" in finalizer
    assert 'sys.platform != "win32"' in backend
    assert "QSystemTrayIcon" in backend and "showMessage" in backend
    assert "Windows-Benachrichtigungen aktivieren" in settings
