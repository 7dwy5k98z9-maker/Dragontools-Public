from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from dragontools.gui.movie_renamer_job_queue import RenamerResolveJobQueue
from dragontools.gui.movie_renamer_resolve_search import MovieRenamerResolveSearchMixin


class _FakeController:
    def __init__(self) -> None:
        self.rows = {"C:/Media/A.mkv": 0}
        self.applied: list[tuple[int, object]] = []

    def find_row_by_path(self, path: str) -> int | None:
        return self.rows.get(path)

    def on_proposal_ready(self, row: int, proposal) -> None:
        self.applied.append((row, proposal))


class _Harness(MovieRenamerResolveSearchMixin):
    def __init__(self) -> None:
        self._request_versions: dict[str, int] = {}
        self.table_controller = _FakeController()
        self.thread = None


def _job(path: str, marker: str, request_id: int = 1) -> tuple:
    return (0, path, "", marker, False, None, request_id)


def test_priority_queue_moves_manual_job_ahead_and_drops_older_same_path():
    queue = RenamerResolveJobQueue([
        _job("C:/Media/A.mkv", "auto-a"),
        _job("C:/Media/B.mkv", "auto-b"),
        _job("C:/Media/C.mkv", "auto-c"),
    ])

    queue.prepend([
        _job("C:/Media/B.mkv", "manual-b", 2),
        _job("C:/Media/D.mkv", "manual-d", 1),
    ])

    markers = [queue.take(grace_seconds=0)[3] for _ in range(4)]
    assert markers == ["manual-b", "manual-d", "auto-a", "auto-c"]


def test_cancel_paths_removes_pending_lookup_without_affecting_other_jobs():
    queue = RenamerResolveJobQueue([
        _job("C:/Media/A.mkv", "a"),
        _job("C:/Media/B.mkv", "b"),
    ])

    assert queue.cancel_paths(["C:/Media/A.mkv"]) == 1
    assert queue.take(grace_seconds=0)[3] == "b"
    assert queue.take(grace_seconds=0) is None


def test_newer_manual_request_makes_older_result_stale():
    harness = _Harness()
    auto = harness._version_jobs([(0, "C:/Media/A.mkv", "", "", False, None)])
    manual = harness._version_jobs([(0, "C:/Media/A.mkv", "series", "A", False, None)])

    harness.on_proposal_ready("C:/Media/A.mkv", auto[0][6], "old")
    harness.on_proposal_ready("C:/Media/A.mkv", manual[0][6], "new")

    assert harness.table_controller.applied == [(0, "new")]


def test_removed_path_ignores_late_worker_result():
    harness = _Harness()
    job = harness._version_jobs([(0, "C:/Media/A.mkv", "", "", False, None)])[0]
    harness.table_controller.rows.clear()
    harness.invalidate_paths(["C:/Media/A.mkv"])

    harness.on_proposal_ready("C:/Media/A.mkv", job[6], "late")

    assert harness.table_controller.applied == []


def test_busy_view_keeps_edit_and_remove_controls_available():
    source = (Path(__file__).resolve().parents[1] / "gui" / "movie_renamer_view_state.py").read_text(encoding="utf-8")
    available = source.split("def available_during_search", 1)[1].split("def set_busy", 1)[0]
    blocked = source.split("def blocked_during_search", 1)[1].split("def available_during_search", 1)[0]

    for name in (
        "manual_series_search_btn",
        "manual_movie_search_btn",
        "show_all_candidates_btn",
        "edit_search_btn",
        "remove_btn",
        "clear_btn",
    ):
        assert name in available
        assert name not in blocked
    assert "rename_btn" in blocked


def test_remove_and_clear_invalidate_searches_before_table_mutation():
    source = (Path(__file__).resolve().parents[1] / "gui" / "movie_renamer_actions.py").read_text(encoding="utf-8")
    remove_body = source.split("def remove_selected", 1)[1].split("def clear", 1)[0]
    clear_body = source.split("def clear", 1)[1]

    assert remove_body.index("invalidate_paths") < remove_body.index("removeRow")
    assert clear_body.index("invalidate_paths") < clear_body.index("setRowCount")
