from __future__ import annotations

from datetime import date, datetime, timedelta
import os


def test_log_cleanup_deletes_old_logs_but_keeps_crash_state(tmp_path):
    from dragontools.core.log_cleanup import cleanup_logs

    old_log = tmp_path / "Logging" / "2026" / "08-August" / "old.txt"
    new_log = tmp_path / "Logging" / "2026" / "08-August" / "new.txt"
    error_log = tmp_path / "Logging" / "2026" / "08-August" / "ErrorReports" / "error.txt"
    crash_log = tmp_path / "Logging" / "2026" / "08-August" / "CrashReports" / "crash.txt"
    crash_state = tmp_path / "Logging" / "2026" / "08-August" / "CrashReports" / "crash_state.json"
    verbose = tmp_path / "VerboseLog" / "verbose.txt"
    for path in (old_log, new_log, error_log, crash_log, crash_state, verbose):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")

    old_ts = (datetime.now() - timedelta(days=10)).timestamp()
    new_ts = datetime.now().timestamp()
    os.utime(old_log, (old_ts, old_ts))
    os.utime(error_log, (old_ts, old_ts))
    os.utime(crash_log, (old_ts, old_ts))
    os.utime(verbose, (old_ts, old_ts))
    os.utime(new_log, (new_ts, new_ts))

    result = cleanup_logs(tmp_path, cutoff_date=date.today() - timedelta(days=5))

    assert result.deleted_files == 4
    assert not old_log.exists()
    assert not error_log.exists()
    assert not crash_log.exists()
    assert not verbose.exists()
    assert new_log.exists()
    assert crash_state.exists()


def test_log_cleanup_respects_selected_categories(tmp_path):
    from dragontools.core.log_cleanup import (
        LOG_CATEGORY_ERROR,
        cleanup_logs,
    )

    normal = tmp_path / "Logging" / "2026" / "08-August" / "normal.txt"
    error = tmp_path / "Logging" / "2026" / "08-August" / "ErrorReports" / "error.txt"
    crash = tmp_path / "Logging" / "2026" / "08-August" / "CrashReports" / "crash.txt"
    verbose = tmp_path / "VerboseLog" / "verbose.txt"
    for path in (normal, error, crash, verbose):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")

    result = cleanup_logs(tmp_path, categories=[LOG_CATEGORY_ERROR])

    assert result.deleted_files == 1
    assert normal.exists()
    assert not error.exists()
    assert crash.exists()
    assert verbose.exists()
