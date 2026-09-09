from __future__ import annotations

from types import SimpleNamespace


class _Button:
    def __init__(self) -> None:
        self.enabled = None
        self.text = ""
        self.tooltip = ""

    def setEnabled(self, value: bool) -> None:
        self.enabled = bool(value)

    def setText(self, value: str) -> None:
        self.text = str(value)

    def setToolTip(self, value: str) -> None:
        self.tooltip = str(value)


class _Bar:
    def __init__(self) -> None:
        self.value = None
        self.format = ""

    def setValue(self, value: int) -> None:
        self.value = int(value)

    def setFormat(self, text: str) -> None:
        self.format = text


class _Label:
    def __init__(self) -> None:
        self.text = ""

    def setText(self, text: str) -> None:
        self.text = str(text)


class _Combo:
    def __init__(self) -> None:
        self.items: list[tuple[str, object]] = []
        self.index = -1
        self.visible = False

    def addItem(self, label: str, data=None) -> None:
        self.items.append((label, data))
        if self.index < 0:
            self.index = 0

    def clear(self) -> None:
        self.items.clear()
        self.index = -1

    def blockSignals(self, _value: bool) -> None:
        return None

    def setCurrentIndex(self, index: int) -> None:
        self.index = int(index)

    def currentData(self):
        return self.itemData(self.index)

    def count(self) -> int:
        return len(self.items)

    def itemData(self, index: int):
        if 0 <= index < len(self.items):
            return self.items[index][1]
        return None

    def setVisible(self, value: bool) -> None:
        self.visible = bool(value)

    def isVisible(self) -> bool:
        return self.visible

    def select_data(self, data) -> None:
        for index, (_label, item_data) in enumerate(self.items):
            if item_data == data:
                self.index = index
                return


class _Worker:
    log_file_path = "run.log"

    def __init__(self) -> None:
        self.started = 0

    def start(self) -> None:
        self.started += 1


class _ParallelWorker:
    def __init__(self) -> None:
        self.positions = {
            r"C:\in\a.mkv": 1,
            r"C:\in\b.mkv": 2,
        }

    def active_file_count(self) -> int:
        return 2

    def aggregate_progress_percent(self) -> int:
        return 16

    def display_position_for_path(self, path: str, *, fallback_idx: int, fallback_total: int):
        return self.positions.get(path, fallback_idx), fallback_total


def test_start_worker_ui_state_uses_initial_progress_and_starts_worker_once(monkeypatch):
    from dragontools.gui.conversion_worker_lifecycle import ConversionWorkerLifecycle

    refresh_calls: list[str] = []
    logs: list[str] = []
    journals: list[tuple[str, list[str]]] = []
    worker = _Worker()
    progress = SimpleNamespace(refresh_queue_after_file_progress=lambda _pct: refresh_calls.append("refresh"))
    ui = SimpleNamespace(
        abort_btn=_Button(),
        progress_bar=_Bar(),
        curlog_btn=_Button(),
    )
    state = SimpleNamespace(current_log_path=None)

    lifecycle = ConversionWorkerLifecycle(
        state=state,
        ui=ui,
        log=lambda text, *args, **kwargs: logs.append(text),
        set_start_enabled=lambda value: logs.append(f"start={value}"),
        refresh_queue=lambda: None,
        result_service=SimpleNamespace(),
        progress_presenter=progress,
        default_codec="h265",
        collect_encoder_options=lambda: {"encoder": "nvenc"},
    )
    monkeypatch.setattr(
        lifecycle,
        "start_job_journal",
        lambda _worker, *, mode, files: journals.append((mode, list(files))),
    )

    lifecycle.start_worker_ui_state(
        worker,
        "Starte Test",
        mode="convert",
        files=["film.mkv"],
    )

    assert worker.started == 1
    assert ui.progress_bar.value == 0
    assert ui.abort_btn.enabled is True
    assert ui.curlog_btn.enabled is True
    assert state.current_log_path == "run.log"
    assert refresh_calls == ["refresh"]
    assert journals == [("convert", ["film.mkv"])]
    assert "Starte Test" in logs


def test_parallel_file_progress_defaults_to_combined_display_and_can_focus_file():
    from dragontools.gui.conversion_progress_presenter import ConversionProgressPresenter

    a_path = r"C:\in\a.mkv"
    b_path = r"C:\in\b.mkv"
    combo = _Combo()
    ui = SimpleNamespace(
        file_lbl=_Label(),
        file_focus_combo=combo,
        file_bar=_Bar(),
        eta_lbl=_Label(),
        total_lbl=_Label(),
        progress_bar=_Bar(),
        file_list=SimpleNamespace(count=lambda: 2),
    )
    state = SimpleNamespace(
        total_files=2,
        completed_inputs=set(),
        thread=_ParallelWorker(),
        last_total_pct=0,
        active_file_progress={},
        active_file_eta={},
        progress_focus_path=None,
        job_journal=None,
        job_journal_current_paths=set(),
    )
    presenter = ConversionProgressPresenter(
        state=state,
        ui=ui,
        log=lambda *_a, **_k: None,
        refresh_queue=lambda: None,
        set_file_list_item_text=lambda _path, _text: None,
    )

    presenter.on_file_progress(a_path, 20, 300)
    assert combo.visible is False
    assert ui.file_bar.value == 20
    assert "a.mkv" in ui.file_lbl.text

    presenter.on_file_progress(b_path, 60, 120)
    assert combo.visible is True
    assert ui.file_bar.value == 40
    assert "2 Dateien parallel aktiv" in ui.file_lbl.text
    assert "Restdauer aktive Dateien" in ui.eta_lbl.text

    combo.select_data(b_path)
    presenter.on_progress_focus_changed()
    assert state.progress_focus_path == b_path
    assert ui.file_bar.value == 60
    assert "b.mkv" in ui.file_lbl.text

    presenter.on_file_result_cleanup(b_path, b_path, "✅")
    assert combo.visible is False
    assert ui.file_bar.value == 20
    assert "a.mkv" in ui.file_lbl.text


def test_single_initial_file_still_uses_parallel_thread_when_limit_is_above_one(monkeypatch):
    from dragontools.gui.conversion_worker_factory import ConversionConfigBuilder, ConversionWorkerFactory

    class _Spin:
        def value(self):
            return 23

    class _Text:
        def currentText(self):
            return "medium"

    class _Scale:
        def currentText(self):
            return "original"

    class _Check:
        def isChecked(self):
            return False

    class FakeParallel:
        def __init__(self, files, config, *, parallel_jobs, parent=None):
            self.files = list(files)
            self.config = config
            self.parallel_jobs = parallel_jobs
            self.parent = parent

    class FakeSingle:
        def __init__(self, files, config, *, parent=None):
            self.files = list(files)
            self.config = config
            self.parent = parent

    monkeypatch.setattr(
        ConversionConfigBuilder,
        "subtitle_rules",
        lambda self: {},
    )

    ui = SimpleNamespace(
        crf_spin=_Spin(),
        preset_combo=_Text(),
        scale_combo=_Scale(),
        over_cb=_Check(),
        strip_cb=_Check(),
    )
    state = SimpleNamespace(file_overrides={})
    builder = ConversionConfigBuilder(
        state=state,
        ui=ui,
        default_codec="h265",
        collect_encoder_options=lambda: {"encoder": "nvenc"},
        get_target_paths=lambda: {},
        log=lambda *_a, **_k: None,
    )
    factory = ConversionWorkerFactory(
        config_builder=builder,
        qt_parent=None,
        converter_cls=FakeSingle,
        parallel_converter_cls=FakeParallel,
    )

    worker = factory.create_converter(
        ["einzeldatei.mkv"],
        encoder_options={"encoder": "nvenc"},
        parallel_jobs=2,
    )

    assert isinstance(worker, FakeParallel)
    assert worker.files == ["einzeldatei.mkv"]
    assert worker.parallel_jobs == 2
    assert worker.config.codec == "h265"
    assert worker.config.encoder_options["encoder"] == "nvenc"


def test_start_convert_delegates_preflight_factory_lifecycle_and_progress(monkeypatch):
    import sys
    import types

    pyqt = types.ModuleType("PyQt6")
    qtcore = types.ModuleType("PyQt6.QtCore")
    qtwidgets = types.ModuleType("PyQt6.QtWidgets")
    qtcore.QSettings = object
    qtwidgets.QMessageBox = object
    monkeypatch.setitem(sys.modules, "PyQt6", pyqt)
    monkeypatch.setitem(sys.modules, "PyQt6.QtCore", qtcore)
    monkeypatch.setitem(sys.modules, "PyQt6.QtWidgets", qtwidgets)
    sys.modules.pop("dragontools.gui.conversion_start_coordinator", None)

    import dragontools.gui.conversion_start_coordinator as module
    from dragontools.gui.conversion_start_coordinator import ConversionStartCoordinator

    events: list[object] = []
    files = ["a.mkv", "b.mkv"]
    worker = object()
    ui = SimpleNamespace(
        file_list=SimpleNamespace(get_paths=lambda: list(files)),
        pause_btn=_Button(),
        progress_bar=_Bar(),
        over_cb=SimpleNamespace(isChecked=lambda: False),
    )
    state = SimpleNamespace(thread=None)
    preflight = SimpleNamespace(
        run_if_needed=lambda values: events.append(("preflight", list(values))) or True,
    )
    progress = SimpleNamespace(
        reset=lambda count: events.append(("reset", count)),
        on_total_progress=lambda pct: None,
    )
    factory = SimpleNamespace(
        create_converter=lambda values, *, encoder_options, parallel_jobs: (
            events.append(("factory", list(values), dict(encoder_options), parallel_jobs)) or worker
        )
    )

    class _Lifecycle:
        def active_worker(self):
            return None

        def connect_worker_signals(self, value, total_progress_slot):
            events.append(("connect", value is worker, total_progress_slot == progress.on_total_progress))

        def start_worker_ui_state(self, value, message, *, mode, files):
            events.append(("start", value is worker, mode, list(files), message))

    monkeypatch.setattr(module, "parallel_jobs_for_encoder", lambda _settings, _encoder: 3)
    monkeypatch.setattr(
        ConversionStartCoordinator,
        "confirm_disk_space",
        lambda self, values, parallel_jobs: events.append(("disk", list(values), parallel_jobs)) or True,
    )

    coordinator = ConversionStartCoordinator(
        state=state,
        ui=ui,
        log=lambda *_a, **_k: None,
        collect_encoder_options=lambda: {"encoder": "nvenc", "cq": 23},
        get_target_paths=lambda: {},
        refresh_queue=lambda: None,
        set_start_enabled=lambda _value: None,
        set_queue_edit=lambda _value: None,
        preflight=preflight,
        worker_factory=factory,
        lifecycle=_Lifecycle(),
        progress_presenter=progress,
        qt_parent=SimpleNamespace(settings=object()),
    )

    coordinator.start_convert()

    assert state.thread is worker
    assert events[0] == ("preflight", files)
    assert ("reset", 2) in events
    assert ("disk", files, 3) in events
    assert ("factory", files, {"encoder": "nvenc", "cq": 23}, 3) in events
    assert ("connect", True, True) in events
    assert any(event[0] == "start" and event[1] is True and event[2] == "convert" for event in events)
    assert ui.pause_btn.enabled is True


def test_start_worker_ui_state_does_not_start_worker_when_job_journal_fails(monkeypatch):
    from dragontools.gui.conversion_worker_lifecycle import ConversionWorkerLifecycle

    logs: list[str] = []
    worker = _Worker()
    progress = SimpleNamespace(refresh_queue_after_file_progress=lambda _pct: None)
    ui = SimpleNamespace(
        abort_btn=_Button(),
        progress_bar=_Bar(),
        curlog_btn=_Button(),
    )
    state = SimpleNamespace(current_log_path=None)
    start_enabled: list[bool] = []

    lifecycle = ConversionWorkerLifecycle(
        state=state,
        ui=ui,
        log=lambda text, *args, **kwargs: logs.append(text),
        set_start_enabled=start_enabled.append,
        refresh_queue=lambda: None,
        result_service=SimpleNamespace(),
        progress_presenter=progress,
        default_codec="h265",
        collect_encoder_options=lambda: {"encoder": "nvenc"},
    )
    monkeypatch.setattr(
        lifecycle,
        "start_job_journal",
        lambda _worker, *, mode, files: False,
    )

    lifecycle.start_worker_ui_state(
        worker,
        "Starte Test",
        mode="convert",
        files=["film.mkv"],
    )

    assert worker.started == 0
    assert ui.abort_btn.enabled is False
    assert start_enabled[-1] is True
    assert any("nicht gestartet" in text for text in logs)
