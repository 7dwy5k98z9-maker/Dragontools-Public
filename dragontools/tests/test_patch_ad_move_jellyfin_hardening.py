from __future__ import annotations

from pathlib import Path

from dragontools.core.move_source_probe import probe_companions, probe_move_source


PACKAGE = Path(__file__).resolve().parents[1]


def test_move_source_probe_retries_and_preserves_oserror_details(tmp_path) -> None:
    sleeps: list[float] = []
    missing = tmp_path / "missing.mkv"

    probe = probe_move_source(
        str(missing),
        attempts=3,
        retry_delay_s=0.25,
        sleeper=sleeps.append,
    )

    assert probe.available is False
    assert probe.attempts == 3
    assert probe.error_type == "FileNotFoundError"
    assert str(missing) in probe.error_message
    assert probe.parent_available is True
    assert sleeps == [0.25, 0.25]


def test_move_source_probe_returns_real_size_for_available_file(tmp_path) -> None:
    source = tmp_path / "episode.mkv"
    source.write_bytes(b"123456789")

    probe = probe_move_source(str(source), sleeper=lambda _delay: None)

    assert probe.available is True
    assert probe.size_bytes == 9
    assert probe.attempts == 1
    assert probe.error_text == ""


def test_companion_probe_keeps_per_path_error_details(tmp_path) -> None:
    existing = tmp_path / "episode.nfo"
    missing = tmp_path / "episode.trickplay"
    existing.write_text("ok", encoding="utf-8")

    result = probe_companions([str(existing), str(missing)])

    assert result[0] == (str(existing), True, "")
    assert result[1][0] == str(missing)
    assert result[1][1] is False
    assert "FileNotFoundError" in result[1][2]


def test_incremental_move_no_longer_discards_temporarily_missing_outputs() -> None:
    source = (PACKAGE / "gui/move_incremental_lifecycle.py").read_text(encoding="utf-8")

    assert "probe_move_source(path)" in source
    assert "bleibt für späteres Verschieben vorgemerkt" in source
    assert "self._state.fertig.discard(path)" not in source
    assert "self._state.sidecar_outputs_by_video.pop(path, None)" not in source
    assert "Geplantes Ziel:" in source
    assert "Companion-Dateien:" in source


def test_move_worker_rechecks_source_instead_of_single_exists_probe() -> None:
    source = (PACKAGE / "worker/move_batch_executor.py").read_text(encoding="utf-8")

    assert "source_probe = probe_move_source(path)" in source
    assert "Move-Quelle auch nach Wiederholungsprüfung nicht erreichbar" in source
    assert "Geplantes Ziel:" in source
    assert "Companion-Dateien:" in source
    assert "if not Path(path).exists():" not in source


def test_jellyfin_fallback_is_logged_as_warning_not_success() -> None:
    source = (PACKAGE / "gui/jellyfin_refresh_dispatch.py").read_text(encoding="utf-8")

    assert "result.fallback_used" in source
    assert "if fallback_used:" in source
    assert 'log(f"⚠️ {message}", "warn")' in source


def test_full_scan_guard_and_scheduled_task_detection_are_release_smoke_covered() -> None:
    from dragontools.core.release_validation_package import _SMOKE_MODULES

    covered = {path.as_posix() for path in _SMOKE_MODULES}
    assert "core/move_source_probe.py" in covered
    assert "core/jellyfin_full_scan_guard.py" in covered
