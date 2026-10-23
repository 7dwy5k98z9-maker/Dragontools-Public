"""Real Qt regressions for preview refreshes after conversion and moves."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QLabel, QProgressBar, QPushButton, QWidget

from dragontools.core.result_status import POSTPROCESS_PENDING_STATUS
from dragontools.gui.conversion_progress_presenter import ConversionProgressPresenter
from dragontools.gui.conversion_result_file_events import ConversionResultFileEventsMixin
from dragontools.gui.conversion_session_state import ConversionSessionState
from dragontools.gui.convert_widget_file_queue import FileListWidget
from dragontools.gui.convert_widget_pipeline_preview import ConvertWidgetPipelinePreview
from dragontools.gui.convert_widget_queue_badges import ConvertWidgetQueueBadgesMixin
from dragontools.gui.file_worker_pause import update_file_pause_row
from dragontools.gui.move_incremental_lifecycle import IncrementalMoveLifecycle
from dragontools.gui.ui_helpers import set_file_list_item_text


class _Owner(ConvertWidgetQueueBadgesMixin, QWidget):
    def _refresh_queue_window(self):
        self.refreshes += 1

    def _cached_preflight_preview(self, path):
        self.preview_reads.append(path)
        return {"pipeline": "standard"}


class _Results(ConversionResultFileEventsMixin):
    def _record_journal_result(self, *args):
        pass

    def _finish_pending_postprocess_run(self):
        pass


@pytest.fixture
def queue(qtbot, tmp_path):
    owner = _Owner()
    qtbot.addWidget(owner)
    owner._state = ConversionSessionState()
    owner.default_codec, owner.settings = "h265", None
    owner.refreshes, owner.preview_reads = 0, []
    owner.file_list = FileListWidget(owner)
    owner._ui = SimpleNamespace(
        file_list=owner.file_list, file_lbl=QLabel(owner), eta_lbl=QLabel(owner),
        file_bar=QProgressBar(owner), progress_bar=QProgressBar(owner),
        total_lbl=QLabel(owner), curlog_btn=QPushButton(owner),
    )
    source = tmp_path / "Deutschland - S02E01 - Tar Baby.mkv"
    source.write_bytes(b"test video")
    owner.file_list.add_path(str(source))
    owner._pipeline_preview = ConvertWidgetPipelinePreview(owner)
    results = _Results()
    results._state, results._ui = owner._state, owner._ui
    results._refresh_queue = owner._refresh_queue_window
    results._log = Mock()
    yield owner, source, results
    owner._pipeline_preview.shutdown()


def _refresh_preview(owner, qtbot):
    previous = owner.refreshes
    owner._pipeline_preview.refresh()
    qtbot.waitUntil(lambda: owner.refreshes > previous, timeout=1500)


@pytest.mark.parametrize("status,caption", [
    ("✅", "✅"), ("❌", "❌"), ("⚠️", "⚠️"), ("⏭️", "⏭️"),
    (POSTPROCESS_PENDING_STATUS, "✳️"),
])
def test_preview_refresh_preserves_worker_results_without_reanalysing(queue, qtbot, status, caption):
    owner, source, results = queue
    owner.update_queue_label(str(source))
    assert "Encode: Standard" in owner.file_list.item(0).text()
    owner.preview_reads.clear()
    results.on_file_result(str(source), str(source), status)
    _refresh_preview(owner, qtbot)
    assert owner.file_list.item(0).text() == f"{caption}  {source.name}"
    assert owner.preview_reads == []


def test_incremental_move_caption_survives_refresh_after_source_disappears(queue, qtbot, tmp_path):
    owner, source, results = queue
    results.on_file_result(str(source), str(source), "✅")
    target = tmp_path / "moved.mkv"
    source.rename(target)
    move = IncrementalMoveLifecycle.__new__(IncrementalMoveLifecycle)
    move._state = owner._state
    move._set_file_text = lambda path, text: set_file_list_item_text(owner.file_list, path, text)
    move._consume_moved_outputs([{"source_path": str(source), "target_path": str(target), "ok": True}])
    assert not owner._state.fertig and not owner._state.artifacts_by_input
    _refresh_preview(owner, qtbot)
    assert owner.file_list.item(0).text() == f"📦 Verschoben  {source.name}"
    assert owner.preview_reads == []


def test_active_eta_and_individual_pause_survive_preview_refresh(queue, qtbot):
    owner, source, _results = queue
    paused = False
    owner._state.thread = SimpleNamespace(file_pause_state=lambda _: paused)
    text = f"⏳ 13:13  {source.name}"
    set_file_list_item_text(owner.file_list, str(source), text)
    _refresh_preview(owner, qtbot)
    assert owner.file_list.item(0).text() == text
    paused = True
    update_file_pause_row(owner.file_list, worker=owner._state.thread, path=str(source))
    _refresh_preview(owner, qtbot)
    assert owner.file_list.item(0).text() == f"⏸ Pausiert · {text}"
    paused = False
    update_file_pause_row(owner.file_list, worker=owner._state.thread, path=str(source))
    _refresh_preview(owner, qtbot)
    assert owner.file_list.item(0).text() == text


def test_new_run_releases_previous_result_and_queued_option_badges(queue, qtbot):
    owner, source, results = queue
    results.on_file_result(str(source), str(source), "✅")
    presenter = ConversionProgressPresenter(
        state=owner._state, ui=owner._ui, log=Mock(), refresh_queue=owner._refresh_queue_window,
        set_file_list_item_text=lambda path, text: set_file_list_item_text(owner.file_list, path, text),
    )
    presenter.reset(1)
    assert owner.file_list.item(0).text() == source.name
    owner._state.file_overrides[str(source)] = {"processing_mode": "strip_only"}
    _refresh_preview(owner, qtbot)
    assert "Verarbeitung: Strip-Only" in owner.file_list.item(0).text()
    assert "✅" not in owner.file_list.item(0).text()
    presenter.on_file_progress(str(source), 10, 60)
    _refresh_preview(owner, qtbot)
    assert owner.file_list.item(0).text() == f"⏳ 01:00  {source.name}"


def test_remove_and_readd_starts_with_fresh_badges(queue, qtbot):
    owner, source, results = queue
    results.on_file_result(str(source), str(source), "❌")
    owner.file_list.remove_path(str(source))
    owner._state.reset_file_for_requeue(str(source))
    owner.file_list.add_path(str(source))
    _refresh_preview(owner, qtbot)
    assert "Encode: Standard" in owner.file_list.item(0).text()
    assert "❌" not in owner.file_list.item(0).text()


def test_delayed_progress_cannot_replace_finished_or_moved_caption(queue, qtbot):
    owner, source, results = queue
    results.on_file_result(str(source), str(source), "✅")
    presenter = ConversionProgressPresenter(
        state=owner._state, ui=owner._ui, log=Mock(), refresh_queue=owner._refresh_queue_window,
        set_file_list_item_text=lambda path, text: set_file_list_item_text(owner.file_list, path, text),
    )
    set_file_list_item_text(owner.file_list, str(source), f"📦 Verschoben  {source.name}")
    presenter.on_file_progress(str(source), 90, 30)
    presenter.on_encode_stage_complete(str(source), str(source))
    _refresh_preview(owner, qtbot)
    assert owner.file_list.item(0).text() == f"📦 Verschoben  {source.name}"


def test_queued_options_keep_updating_without_runtime_status(queue, qtbot):
    owner, source, _results = queue
    _refresh_preview(owner, qtbot)
    assert "Encode: Standard" in owner.file_list.item(0).text()
    owner._state.file_overrides[str(source)] = {"processing_mode": "strip_only"}
    _refresh_preview(owner, qtbot)
    assert "Verarbeitung: Strip-Only" in owner.file_list.item(0).text()


def test_preview_result_arriving_after_completion_keeps_checkmark(queue):
    from dragontools.core.transaction_identity import stat_identity
    owner, source, results = queue
    job = {"path": str(source), "identity": stat_identity(source), "key": "earlier-preview"}
    results.on_file_result(str(source), str(source), "✅")
    owner._pipeline_preview._accept_result((job, None, {"pipeline": "dv"}, ""))
    assert owner.file_list.item(0).text() == f"✅  {source.name}"
