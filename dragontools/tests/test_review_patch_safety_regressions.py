from __future__ import annotations

import sqlite3
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from dragontools.core.media_library_db import initialize_database
from dragontools.core.media_library_repository_moves import _deactivate_existing_episode_identity
from dragontools.core.media_library_schema import UnsupportedMediaLibrarySchemaError
from dragontools.core.move_copy_verification import verify_staged_file_copy
from dragontools.worker.audio_video_match_render import validate_output
from dragontools.worker.converter_process_executor import ConverterProcessExecutor


def _insert_episode(
    conn: sqlite3.Connection,
    *,
    path: Path,
    series_title: str,
    year: int | None,
    season: int = 1,
    episode: int = 1,
) -> None:
    conn.execute(
        """
        INSERT INTO media_items(
            item_type, title, series_title, season, episode, year,
            path, parent_path, filename, normalized_title,
            exists_flag, active, created_at, updated_at
        ) VALUES('episode', ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, 'now', 'now')
        """,
        (
            path.stem,
            series_title,
            season,
            episode,
            year,
            str(path),
            str(path.parent),
            path.name,
            "ranma 1 2",
        ),
    )


def test_future_media_library_schema_is_rejected_without_rewrite(tmp_path: Path) -> None:
    db = tmp_path / "future.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO meta(key, value) VALUES('schema_version', '999')")
        conn.execute("CREATE TABLE future_only_marker(value TEXT)")
        conn.execute("INSERT INTO future_only_marker(value) VALUES('keep')")

    with pytest.raises(UnsupportedMediaLibrarySchemaError, match="Schema 999"):
        initialize_database(db)

    with sqlite3.connect(db) as conn:
        version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
        marker = conn.execute("SELECT value FROM future_only_marker").fetchone()[0]
        media_items = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='media_items'"
        ).fetchone()
    assert version == "999"
    assert marker == "keep"
    assert media_items is None


def test_episode_replacement_does_not_cross_series_release_year(tmp_path: Path) -> None:
    db = initialize_database(tmp_path / "library.sqlite3")
    old_1989 = tmp_path / "Anime" / "Ranma 1-2 (1989)" / "Staffel 01" / "Ranma 1-2 - S01E01.mkv"
    old_2024 = tmp_path / "Anime" / "Ranma 1-2 (2024)" / "Staffel 01" / "Ranma 1-2 - S01E01.mkv"
    new_2024 = tmp_path / "Neu" / "Ranma 1-2 (2024)" / "Staffel 01" / "Ranma 1-2 - S01E01.mkv"

    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        _insert_episode(conn, path=old_1989, series_title="Ranma 1-2", year=1989)
        _insert_episode(conn, path=old_2024, series_title="Ranma 1-2", year=2024)
        item = {
            "item_type": "episode",
            "path": str(new_2024),
            "parent_path": str(new_2024.parent),
            "filename": new_2024.name,
            "series_title": "Ranma 1-2",
            "normalized_title": "ranma 1 2",
            "season": 1,
            "episode": 1,
            "year": 2024,
        }
        changed = _deactivate_existing_episode_identity(conn, item)
        rows = conn.execute(
            "SELECT year, active, exists_flag FROM media_items ORDER BY year"
        ).fetchall()

    assert changed == 1
    assert [tuple(row) for row in rows] == [(1989, 1, 1), (2024, 0, 0)]


def test_episode_replacement_without_year_does_not_cross_different_series_roots(tmp_path: Path) -> None:
    db = initialize_database(tmp_path / "library.sqlite3")
    old_path = tmp_path / "AnimeA" / "Testserie" / "Staffel 01" / "Testserie - S01E01.mkv"
    new_path = tmp_path / "AnimeB" / "Testserie" / "Staffel 01" / "Testserie - S01E01.mkv"
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            INSERT INTO media_items(
                item_type, title, series_title, season, episode, path, parent_path,
                filename, normalized_title, exists_flag, active, created_at, updated_at
            ) VALUES('episode', 'Alt', 'Testserie', 1, 1, ?, ?, ?, 'testserie', 1, 1, 'now', 'now')
            """,
            (str(old_path), str(old_path.parent), old_path.name),
        )
        changed = _deactivate_existing_episode_identity(
            conn,
            {
                "item_type": "episode",
                "path": str(new_path),
                "parent_path": str(new_path.parent),
                "filename": new_path.name,
                "series_title": "Testserie",
                "normalized_title": "testserie",
                "season": 1,
                "episode": 1,
                "year": None,
            },
        )
        active = conn.execute("SELECT active FROM media_items").fetchone()[0]
    assert changed == 0
    assert active == 1


class _PausedWorker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current_process = None
        self._paused = True
        self._pause_ev = threading.Event()
        self.abort_requested = False
        self.abort_type = None
        self.messages: list[tuple[str, str]] = []

    def log(self, message: str, level: str = "info") -> None:
        self.messages.append((message, level))


@pytest.mark.parametrize("capture", [False, True])
def test_converter_process_timeout_excludes_pause_time(capture: bool) -> None:
    worker = _PausedWorker()
    executor = ConverterProcessExecutor(worker)
    result: list[object] = []

    def run_process() -> None:
        cmd = [sys.executable, "-c", "import time; time.sleep(0.15); print('ok')"]
        if capture:
            result.append(executor.run_capture(cmd, timeout_s=2.0, label="Pause-Test"))
        else:
            result.append(executor.run(cmd, timeout_s=2.0, label="Pause-Test"))

    thread = threading.Thread(target=run_process)
    thread.start()
    time.sleep(2.4)  # longer than the configured timeout, but entirely paused
    worker._paused = False
    worker._pause_ev.set()
    thread.join(timeout=5)

    assert not thread.is_alive()
    if capture:
        rc, stdout, _stderr = result[0]
        assert rc == 0
        assert "ok" in stdout
    else:
        assert result == [0]


def test_avmatch_output_validation_fails_closed_when_probe_fails(tmp_path: Path, monkeypatch) -> None:
    from dragontools.worker import audio_video_match_render as module

    output = tmp_path / "out.mkv"
    output.write_bytes(b"valid-looking-container-bytes")

    def fail_probe(*_args, **_kwargs):
        raise OSError("probe kaputt")

    monkeypatch.setattr(module, "analyze_media", fail_probe)
    with pytest.raises(RuntimeError, match="nicht validiert"):
        validate_output(output, SimpleNamespace(), target_duration_s=100.0)


def test_staged_copy_verification_detects_equal_size_corruption(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    staged = tmp_path / "staged.bin"
    source.write_bytes(b"A" * 4096)
    staged.write_bytes(b"A" * 2048 + b"B" + b"A" * 2047)

    with pytest.raises(OSError, match="Integritätsprüfung"):
        verify_staged_file_copy(source, staged)


def test_run_tool_bytes_timeout_excludes_pause_time() -> None:
    from dragontools.worker.tool_runner import run_tool_bytes

    worker = _PausedWorker()
    result: list[object] = []

    def run_process() -> None:
        result.append(
            run_tool_bytes(
                [sys.executable, "-c", "import time; time.sleep(0.15); print('ok')"],
                label="Binary-Pause-Test",
                timeout_s=2.0,
                worker=worker,
            )
        )

    thread = threading.Thread(target=run_process)
    thread.start()
    time.sleep(2.4)  # longer than timeout, but entirely paused
    worker._paused = False
    worker._pause_ev.set()
    thread.join(timeout=5)

    assert not thread.is_alive()
    run_result = result[0]
    assert run_result.returncode == 0
    assert run_result.timed_out is False
    assert b"ok" in run_result.stdout
