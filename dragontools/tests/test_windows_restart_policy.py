from __future__ import annotations


def test_windows_restart_policy_blocks_running_jobs_and_mentions_shutdown_after():
    from dragontools.core.windows_restart_policy import ACTION_BLOCK, decide_windows_restart_request

    decision = decide_windows_restart_request(
        ("ConverterThread", "MoveThread"),
        shutdown_after_enabled=True,
        interaction_allowed=True,
    )

    assert decision.action == ACTION_BLOCK
    assert decision.active_workers == ("ConverterThread", "MoveThread")
    assert "Herunterfahren nach Abschluss" in decision.message
    assert "danach herunter" in decision.block_reason


def test_windows_restart_policy_asks_only_when_idle_and_interaction_is_allowed():
    from dragontools.core.windows_restart_policy import ACTION_ASK, decide_windows_restart_request

    decision = decide_windows_restart_request(
        (),
        shutdown_after_enabled=False,
        interaction_allowed=True,
    )

    assert decision.action == ACTION_ASK
    assert "läuft aktuell kein Job" in decision.message


def test_windows_restart_policy_blocks_without_dialog_or_during_snooze():
    from dragontools.core.windows_restart_policy import ACTION_BLOCK, decide_windows_restart_request

    no_dialog = decide_windows_restart_request(
        (),
        shutdown_after_enabled=False,
        interaction_allowed=False,
    )
    snoozed = decide_windows_restart_request(
        (),
        shutdown_after_enabled=False,
        interaction_allowed=True,
        snoozed=True,
    )

    assert no_dialog.action == ACTION_BLOCK
    assert snoozed.action == ACTION_BLOCK
    assert "vorübergehend verschoben" in snoozed.block_reason


def test_user_initiated_shutdown_marker_can_be_cleared():
    from dragontools.core.windows_restart_policy import (
        allow_user_initiated_shutdown,
        clear_user_initiated_shutdown,
        user_initiated_shutdown_allowed,
    )

    clear_user_initiated_shutdown()
    assert user_initiated_shutdown_allowed() is False
    allow_user_initiated_shutdown(seconds=1)
    assert user_initiated_shutdown_allowed() is True
    clear_user_initiated_shutdown()
    assert user_initiated_shutdown_allowed() is False
