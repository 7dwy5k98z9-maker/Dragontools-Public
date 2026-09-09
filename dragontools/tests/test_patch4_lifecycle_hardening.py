from __future__ import annotations

import ast
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
GUI_ROOT = PACKAGE_ROOT / "gui"


def test_crash_guard_parallel_mark_activity_is_race_free(tmp_path, monkeypatch):
    from dragontools.core import crash_guard

    state_file = tmp_path / "crash_state.json"
    monkeypatch.setattr(crash_guard, "_state_file", state_file)

    def write(index: int) -> bool:
        return crash_guard.mark_activity(f"parallel-{index}", extra={"index": index})

    with ThreadPoolExecutor(max_workers=24) as pool:
        results = list(pool.map(write, range(80)))

    assert all(results)
    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert data["active"] is True
    assert data["stage"].startswith("parallel-")
    assert isinstance(data["extra"]["index"], int)
    assert list(tmp_path.glob("*.tmp")) == []


def test_crash_guard_uses_shared_atomic_json_writer():
    source = (PACKAGE_ROOT / "core" / "crash_guard.py").read_text(encoding="utf-8")
    assert "atomic_write_json(_state_file, data)" in source
    assert "with _state_lock:" in source
    assert 'with_suffix(".tmp")' not in source


class _AbortWorker:
    def __init__(self, events: list[str], name: str = "abort") -> None:
        self.events = events
        self.running = True
        self.name = name

    def isRunning(self):
        return self.running

    def request_abort(self, mode="sofort"):
        self.events.append(f"stop:{self.name}:{mode}")

    def wait(self, _timeout_ms):
        self.events.append(f"wait:{self.name}")
        self.running = False
        return True

    def objectName(self):
        return self.name


class _CancelWorker(_AbortWorker):
    request_abort = None

    def cancel(self):
        self.events.append(f"stop:{self.name}:cancel")


class _InterruptWorker(_AbortWorker):
    request_abort = None

    def requestInterruption(self):
        self.events.append(f"stop:{self.name}:interrupt")


class _StubbornWorker(_AbortWorker):
    def wait(self, _timeout_ms):
        self.events.append(f"wait:{self.name}")
        return False


def test_application_shutdown_requests_all_workers_before_waiting():
    from dragontools.gui.application_shutdown import shutdown_workers

    events: list[str] = []
    workers = [
        _AbortWorker(events, "a"),
        _CancelWorker(events, "b"),
        _InterruptWorker(events, "c"),
    ]
    result = shutdown_workers(workers, timeout_ms=1000)

    assert result.ok is True
    assert result.requested == 3
    assert result.stopped == 3
    first_wait = next(i for i, item in enumerate(events) if item.startswith("wait:"))
    assert all(item.startswith("stop:") for item in events[:first_wait])
    assert "stop:a:sofort" in events
    assert "stop:b:cancel" in events
    assert "stop:c:interrupt" in events


def test_application_shutdown_never_force_terminates_stubborn_thread():
    from dragontools.gui.application_shutdown import shutdown_workers

    events: list[str] = []
    worker = _StubbornWorker(events, "stubborn")
    result = shutdown_workers([worker], timeout_ms=1)

    assert result.ok is False
    assert result.still_running == ("stubborn",)
    assert not hasattr(worker, "terminate_called")


def test_loaded_widget_collection_uses_public_worker_provider_only():
    from dragontools.gui.application_shutdown import collect_shutdown_workers

    worker = object()

    class Widget:
        def iter_shutdown_workers(self):
            return (worker, worker)

    assert collect_shutdown_workers([Widget(), None]) == [worker]


def _class_methods(path: Path, class_name: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    return {node.name for node in cls.body if isinstance(node, ast.FunctionDef)}


def test_all_lazy_main_tabs_expose_shutdown_worker_contract():
    classes = {
        "convert_widget.py": "ConvertWidget",
        "iso_widget.py": "ISOWidget",
        "merge_widget.py": "MergeWidget",
        "mp4_remux_widget.py": "MP4RemuxWidget",
        "audio_muxer_widget.py": "AudioMuxerWidget",
        "audio_video_matcher_widget.py": "AudioVideoMatcherWidget",
        "subtitle_widget.py": "SubtitleWidget",
        "movie_renamer_widget.py": "MovieRenamerWidget",
        "quality_tester_widget.py": "QualityTesterWidget",
    }
    for filename, class_name in classes.items():
        assert "iter_shutdown_workers" in _class_methods(GUI_ROOT / filename, class_name), filename


def test_subtitle_widget_has_per_job_worker_registry_and_targeted_cancel():
    source = (GUI_ROOT / "subtitle_widget.py").read_text(encoding="utf-8")
    assert "self._workers: dict[str, _SubWorker]" in source
    assert 'self._cancel_worker("extract")' in source
    assert 'self._cancel_worker("inject")' in source
    assert "key=mode" in source
    assert "self._worker =" not in source
    assert "worker.finished.connect(worker.deleteLater)" in source


def test_main_window_shutdown_is_fail_closed_and_clears_crash_marker_after_workers_stop():
    source = (GUI_ROOT / "main_window.py").read_text(encoding="utf-8")
    close_pos = source.index("def closeEvent")
    block = source[close_pos:]
    assert "shutdown_loaded_widgets" in block
    assert "if not result.ok:" in block
    assert "e.ignore()" in block
    assert block.index("clear_activity()") > block.index("if not result.ok:")
    assert "QThread.terminate" not in block
