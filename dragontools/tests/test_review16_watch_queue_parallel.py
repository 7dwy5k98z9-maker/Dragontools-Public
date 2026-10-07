from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from dragontools.core.job_journal import JobJournal, build_resume_plan
from dragontools.core.path_syntax import path_compare_key
from dragontools.core.watch_folder import WatchFolderRule, WatchFolderScanner
from dragontools.worker.parallel_converter_queue import ParallelConverterQueueMixin
from dragontools.worker.parallel_converter_state import (
    ParallelQueueState,
    ParallelResultState,
    ParallelWorkerRegistry,
)
from dragontools.worker.parallel_worker_launcher import ParallelWorkerLauncher


class _Signal:
    def __init__(self) -> None:
        self.slots = []
        self.events = []

    def connect(self, slot) -> None:
        self.slots.append(slot)

    def emit(self, *args) -> None:
        self.events.append(args)
        for slot in list(self.slots):
            slot(*args)


class _Logger:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def info(self, text: str) -> None:
        self.lines.append(text)

    def warn(self, text: str) -> None:
        self.lines.append(text)

    def error(self, text: str) -> None:
        self.lines.append(text)


class _StartFailWorker:
    def __init__(self, files, config, **_kwargs) -> None:
        self.files = list(files)
        self.config = config
        self.log_line = _Signal()
        self.worker_event = _Signal()
        self.file_progress = _Signal()
        self.file_result = _Signal()
        self.progress = _Signal()
        self.finished = _Signal()

    def start(self) -> None:
        raise RuntimeError("start failed")

    def pause(self) -> None:
        pass

    def request_abort(self, _mode: str) -> None:
        pass


def _watch_rule(root: Path) -> WatchFolderRule:
    rule = WatchFolderRule.from_mapping(
        {
            "rule_id": "review16",
            "name": "Review16",
            "path": str(root),
            "recursive": True,
            "codec": "h265",
            "auto_start": True,
            "enabled": True,
        }
    )
    assert rule is not None
    return rule


def test_watch_success_does_not_acknowledge_external_change_when_output_is_elsewhere(tmp_path: Path) -> None:
    watch_root = tmp_path / "watch"
    watch_root.mkdir()
    source = watch_root / "episode.mkv"
    source.write_bytes(b"first revision")
    rule = _watch_rule(watch_root)
    scanner = WatchFolderScanner(stable_seconds=0)
    candidate = scanner.scan([rule], now=0)[0]

    # The watched source changes while the already queued conversion is running.
    source.write_bytes(b"second revision that was never converted")
    output = tmp_path / "encoded" / "episode.mkv"
    output.parent.mkdir()
    output.write_bytes(b"converted first revision")

    scanner.acknowledge_success(candidate, output_path=str(output))

    # Only the old queued signature may be acknowledged. The newer source must
    # be offered again instead of silently disappearing from the watch queue.
    changed = scanner.scan([rule], now=1)
    assert [item.path for item in changed] == [str(source.resolve())]
    assert changed[0].signature != candidate.signature


def test_watch_success_acknowledges_final_signature_for_in_place_output(tmp_path: Path) -> None:
    source = tmp_path / "episode.mkv"
    source.write_bytes(b"before")
    rule = _watch_rule(tmp_path)
    scanner = WatchFolderScanner(stable_seconds=0)
    candidate = scanner.scan([rule], now=0)[0]

    source.write_bytes(b"after-strip-only")
    final_signature = scanner.acknowledge_success(candidate, output_path=str(source))

    assert final_signature != candidate.signature
    assert scanner.scan([rule], now=1) == []


def test_job_journal_uses_windows_case_insensitive_identity_cross_platform(tmp_path: Path) -> None:
    upper = r"C:\Media\Show\Episode.mkv"
    lower = r"c:\media\show\EPISODE.MKV"
    assert path_compare_key(upper) == path_compare_key(lower)

    journal = JobJournal.start(
        files=[upper, lower],
        codec="h265",
        mode="convert",
        root=tmp_path,
    )
    assert journal.data["queue_order"] == [upper]
    assert list(journal.data["files"]) == [upper]

    # A casing variant from a later GUI/worker callback must update the same row
    # and the same current-file ownership, not create a second resume item.
    journal.start_file(lower)
    assert len(journal.data["current_files"]) == 1
    journal.update_queue_order([lower, upper])
    assert journal.data["queue_order"] == [lower]
    journal.finish_file(upper, status="✅")
    assert journal.data["current_files"] == []
    assert list(journal.data["files"]) == [upper]
    assert journal.data["files"][upper]["status"] == "ok"

    plan = build_resume_plan(
        {
            "files": {upper: {"status": "running"}},
            "queue_order": [lower, upper],
        }
    )
    assert plan["files"] == [lower]


def test_parallel_launcher_rolls_back_ownership_if_child_never_starts() -> None:
    path = r"C:\Media\Episode.mkv"
    queue = ParallelQueueState([path])
    results = ParallelResultState()
    registry = ParallelWorkerRegistry(queue, results)
    launcher = ParallelWorkerLauncher(
        worker_factory=_StartFailWorker,
        logger=_Logger(),
        registry=registry,
        queue_state=queue,
    )

    from dragontools.worker.converter_config import ConverterConfig
    config = ConverterConfig(
        codec="h265", crf=23, preset="medium", scale_mode="original",
        overwrite_original=False, encoder_options={}, file_overrides={}, subtitle_rules={}
    )
    kwargs = dict(
        config=config,
        encoder_options={},
        file_overrides={},
        subtitle_rules={},
        parent=None,
        paused=False,
        abort_requested=False,
        abort_type=None,
        log_emit=lambda *_: None,
        event_emit=lambda *_: None,
        relay_crop_decision=lambda *_: None,
        on_file_progress=lambda *_: None,
        on_file_result=lambda *_: None,
        on_encode_stage_complete=lambda *_: None,
        dv_postprocess_gate=None,
        emit_progress=lambda *_: None,
        on_finished=lambda *_: None,
    )

    try:
        launcher.start([path], **kwargs)
    except RuntimeError as exc:
        assert str(exc) == "start failed"
    else:  # pragma: no cover - safety assertion
        raise AssertionError("worker start failure must propagate")

    assert registry.workers == []
    assert registry.active_workers == set()
    assert registry.postprocessing_workers == set()
    assert queue.assigned == {}


class _QueueOwner(ParallelConverterQueueMixin):
    def __init__(self) -> None:
        self._running = True
        self.abort_requested = False
        self._paused = False
        self.parallel_jobs = 1
        self._queue_state = ParallelQueueState(["broken.mkv"])
        self._result_state = ParallelResultState()
        self._registry = ParallelWorkerRegistry(self._queue_state, self._result_state)
        self._logger = _Logger()
        self.file_result = _Signal()
        self.file_overrides = {}

    @property
    def files(self):
        return self._queue_state.files

    @files.setter
    def files(self, value):
        self._queue_state.files = list(value)

    @property
    def _pending_files(self):
        return self._queue_state.pending_files

    @property
    def _active_workers(self):
        return self._registry.active_workers

    @property
    def _assigned(self):
        return self._queue_state.assigned

    @property
    def _terminal_inputs(self):
        return self._queue_state.terminal_inputs

    @property
    def _synthetic_failures(self):
        return self._result_state.synthetic_failures

    @_synthetic_failures.setter
    def _synthetic_failures(self, value):
        self._result_state.synthetic_failures = int(value)

    def _start_child_worker(self, _files):
        raise RuntimeError("no thread resources")

    def _rebuild_display_positions(self):
        self._queue_state.rebuild_display_positions()


def test_pending_worker_start_failure_becomes_terminal_instead_of_losing_path() -> None:
    owner = _QueueOwner()
    owner._start_pending_workers()

    assert owner._pending_files == []
    assert owner._terminal_inputs == {"broken.mkv"}
    assert owner._assigned == {}
    assert owner._synthetic_failures == 1
    assert owner._result_state.failure_details["broken.mkv"]["strategy"] == "parallel_worker_start"
    assert owner.file_result.events == [("broken.mkv", "broken.mkv", "❌")]

from dragontools.worker.parallel_converter_control import ParallelConverterControlMixin


class _ReadOnlyAbortWorker:
    def __init__(self) -> None:
        self._abort_requested = True
        self._abort_type = "nach_datei"
        self.clear_calls = 0

    @property
    def abort_requested(self):
        return self._abort_requested

    @property
    def abort_type(self):
        return self._abort_type

    def clear_abort_request(self) -> bool:
        self.clear_calls += 1
        self._abort_requested = False
        self._abort_type = None
        return True


class _AbortOwner(ParallelConverterControlMixin):
    def __init__(self) -> None:
        self.abort_requested = True
        self.abort_type = "nach_datei"
        self._workers = [_ReadOnlyAbortWorker()]
        self._logger = _Logger()
        self._running = False
        self._paused = False

    def _emit_aggregate_progress(self):
        pass

    def _finish_if_done(self):
        pass

    def _start_pending_workers(self):
        pass


def test_parallel_clear_abort_uses_child_public_api_for_read_only_properties() -> None:
    owner = _AbortOwner()
    child = owner._workers[0]

    assert owner.clear_abort_request() is True
    assert owner.abort_requested is False
    assert owner.abort_type is None
    assert child.clear_calls == 1
    assert child.abort_requested is False
    assert child.abort_type is None


def test_job_journal_roundtrips_per_file_overrides_for_resume(tmp_path: Path) -> None:
    first = r"C:\Media\A.mkv"
    second = r"C:\Media\B.mkv"
    journal = JobJournal.start(
        files=[first, second],
        codec="h265",
        mode="convert",
        file_overrides={
            first: {"processing_mode": "strip_only", "preserve_dv": False},
            second: {"encoder_profile": {"key": "anime_h265", "label": "Anime"}},
        },
        root=tmp_path,
    )

    # A live edit of a waiting file must become durable before that file starts.
    journal.update_file_override(
        second,
        {"encoder_profile": {"key": "anime_h265", "label": "Anime"}, "imax": True},
    )
    plan = build_resume_plan(journal.data)

    assert plan["file_overrides"][first]["processing_mode"] == "strip_only"
    assert plan["file_overrides"][first]["preserve_dv"] is False
    assert plan["file_overrides"][second]["encoder_profile"]["key"] == "anime_h265"
    assert plan["file_overrides"][second]["imax"] is True


def test_resume_plan_carries_journal_path_and_recovery_restores_overrides(tmp_path: Path) -> None:
    source = tmp_path / "resume.mkv"
    source.write_bytes(b"video")
    journal = JobJournal.start(
        files=[str(source)],
        codec="h265",
        mode="convert",
        file_overrides={str(source): {"processing_mode": "strip_only"}},
        root=tmp_path / "journal-root",
    )
    data = dict(journal.data)
    data["_journal_path"] = str(journal.path)
    plan = build_resume_plan(data)
    assert plan["journal_path"] == str(journal.path)

    from dragontools.gui.convert_widget_recovery import ConvertWidgetRecoveryService

    class _FileList:
        def __init__(self) -> None:
            self.paths: list[str] = []
        def add_path(self, path: str) -> bool:
            if path in self.paths:
                return False
            self.paths.append(path)
            return True
        def count(self) -> int:
            return len(self.paths)
        def get_paths(self) -> list[str]:
            return list(self.paths)

    state = SimpleNamespace(
        start_reserved=False,
        file_overrides={},
        total_files=0,
        planned_targets={},
        sidecar_outputs_by_video={},
        restored_move_context={},
        restored_job_journal_path="",
    )
    files = _FileList()
    service = ConvertWidgetRecoveryService(
        state=state,
        file_list=files,
        log=lambda *_: None,
        active_worker=lambda: None,
        refresh_queue=lambda: None,
        update_label=lambda _path: None,
        default_codec="h265",
        get_subtitle_rules=lambda: {},
        overwrite_original=lambda: False,
        get_tools=lambda: {},
    )
    result = service.restore_job_files(
        plan["files"],
        file_overrides=plan["file_overrides"],
        journal_path=plan["journal_path"],
    )
    assert result["added"] == 1
    assert state.restored_job_journal_path == str(journal.path)
    assert state.file_overrides[str(source)]["processing_mode"] == "strip_only"
    # Loading into RAM must not destroy the only durable recovery record.
    assert journal.path.exists()


def test_restored_journal_is_archived_only_after_restart_is_committed(tmp_path: Path) -> None:
    source = tmp_path / "resume.mkv"
    source.write_bytes(b"video")
    journal = JobJournal.start(files=[str(source)], codec="h265", mode="convert", root=tmp_path)

    from dragontools.gui.conversion_worker_lifecycle import ConversionWorkerLifecycle

    lifecycle = object.__new__(ConversionWorkerLifecycle)
    lifecycle._state = SimpleNamespace(restored_job_journal_path=str(journal.path))
    lifecycle._log = lambda *_: None

    assert journal.path.exists()
    assert lifecycle._archive_restored_job_journal(status="resumed_by_run") is True
    assert lifecycle._state.restored_job_journal_path == ""
    assert not journal.path.exists()


def test_job_journal_owner_guard_is_pid_exact():
    from dragontools.core.job_journal_storage import job_journal_owned_by_process

    assert job_journal_owned_by_process({"pid": 4242}, pid=4242) is True
    assert job_journal_owned_by_process({"pid": 4242}, pid=4243) is False
    assert job_journal_owned_by_process({"pid": 0}, pid=4242) is False
    assert job_journal_owned_by_process({"pid": "broken"}, pid=4242) is False


def test_recovery_ui_checks_current_process_journal_before_dialog():
    source = (
        Path(__file__).parents[1] / "gui" / "main_window_recovery.py"
    ).read_text(encoding="utf-8")
    section = source.split("def _show_unfinished_job_journal", 1)[1]
    guard = section.index("job_journal_owned_by_process(data)")
    dialog = section.index("JobResumeDialog(data, self)")
    assert guard < dialog
