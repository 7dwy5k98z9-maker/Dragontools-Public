"""Real Qt and service regressions for queue/profile/preflight contracts."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from PyQt6 import sip
from PyQt6.QtCore import QEvent, QMimeData, QPointF, Qt, QUrl
from PyQt6.QtGui import QDropEvent
from PyQt6.QtWidgets import QCheckBox, QComboBox, QDialog, QSpinBox, QVBoxLayout, QWidget


def _series(qtbot):
    from dragontools.gui.preflight_series_widget import SeriesGroupWidget
    dialog = QDialog()
    qtbot.addWidget(dialog)
    widget = SeriesGroupWidget('Example', [{'path': 'Example.S01E01.mkv', 'season': 1, 'year': 2024}],
                               r'D:\TV', r'D:\Anime', default_type='TV', parent=dialog)
    QVBoxLayout(dialog).addWidget(widget)
    dialog.show()
    widget.apply_existing_series_dir_choices(series_name='Example', choices=[
        {'path': r'D:\TV\Example (1990)', 'base': r'D:\TV', 'base_type': 'TV'},
        {'path': r'D:\TV\Example (2024)', 'base': r'D:\TV', 'base_type': 'TV'},
    ])
    return dialog, widget


@pytest.mark.parametrize('index, fragment', [(1, '1990'), (2, '2024'), (3, 'Example\\Staffel 01')])
def test_series_choice_survives_accepted_hidden_dialog(qtbot, index, fragment):
    dialog, widget = _series(qtbot)
    widget._folder_choice_combo.setCurrentIndex(index)
    expected = widget.get_planned_targets()
    assert fragment in next(iter(expected.values()))
    dialog.accept()
    assert not widget._folder_choice_combo.isVisible()
    assert widget.get_planned_targets() == expected


def test_series_missing_choice_still_requires_selection_when_parent_hidden(qtbot):
    dialog, widget = _series(qtbot)
    dialog.hide()
    assert widget.validate()[0] is False


def test_series_choice_invalidated_by_area_change(qtbot):
    dialog, widget = _series(qtbot)
    widget._folder_choice_combo.setCurrentIndex(2)
    widget._type_combo.setCurrentIndex(1)
    assert next(iter(widget.get_planned_targets().values())).startswith('D:\\Anime\\')


def test_hidden_series_name_edit_revokes_old_choice(qtbot):
    dialog, widget = _series(qtbot)
    widget._folder_choice_combo.setCurrentIndex(2)
    dialog.hide()
    widget._series_edit.setText('Different (2026)')
    assert 'Different (2026)' in next(iter(widget.get_planned_targets().values()))


def test_preflight_keeps_different_series_years_separate(qtbot, monkeypatch):
    from dragontools.gui.preflight_dialog import PreFlightDialog
    monkeypatch.setattr(PreFlightDialog, '_start_online_metadata_lookup', lambda self: None)
    dialog = PreFlightDialog(['Example.1990.S01E01.mkv', 'Example.2024.S01E02.mkv'],
                             r'D:\TV', r'D:\Anime', None)
    qtbot.addWidget(dialog)
    assert len(dialog._widgets) == 2
    assert sorted(w.metadata_lookup_job()[2]['year'] for w in dialog._widgets) == [1990, 2024]


def _encoder(qtbot, codec='h265', best='nvenc', settings=None):
    from dragontools.gui.encoder_settings_controller import EncoderSettingsController
    from dragontools.gui.encoder_settings_state import EncoderSettingsState
    from dragontools.gui.encoder_settings_ui import EncoderSettingsUI
    from dragontools.tests.test_encoder_settings_shutdown import _Settings
    ui = EncoderSettingsUI(default_codec=codec)
    panels = [ui.build_nvenc_panel(), ui.build_qsv_panel(), ui.build_amf_panel(), ui.build_x265_panel()]
    for panel in panels:
        qtbot.addWidget(panel)
    widgets = ui.widgets
    widgets.encoder_combo = QComboBox()
    widgets.encoder_combo.addItems(['cpu', 'auto', 'nvenc', 'qsv', 'amf'])
    widgets.scale_combo = QComboBox()
    widgets.scale_combo.addItems(['original', '4K (2160p)', '1080p', '720p', '480p'])
    widgets.preset_combo = QComboBox()
    widgets.preset_combo.addItems(['medium', 'slow', '6'])
    widgets.crf_spin = QSpinBox()
    widgets.crf_spin.setRange(0, 63)
    widgets.crf_spin.setValue(22)
    for name in ('strip_cb', 'over_cb', 'move_cb', 'shut_cb', 'autocrop_cb', 'imax_detect_cb',
                 'preserve_dv_cb', 'preserve_hdrplus_cb'):
        setattr(widgets, name, QCheckBox())
    widgets.autocrop_cb.setChecked(True)
    widgets.preserve_dv_cb.setChecked(True)
    widgets.preserve_hdrplus_cb.setChecked(True)
    widgets.enc_grp = QWidget()
    widgets.nvenc_p, widgets.qsv_p, widgets.amf_p, widgets.x265_p = panels
    for value in vars(widgets).values():
        if isinstance(value, QWidget) and value.parent() is None:
            qtbot.addWidget(value)
    controller = EncoderSettingsController(default_codec=codec, settings=settings or _Settings(),
        state=EncoderSettingsState(), ui=ui, profile_service=SimpleNamespace(),
        log=lambda *a: None, resolve_best_encoder=lambda: best)
    controller.connect_encoder_settings_signals()
    return controller


def test_cpu_profile_restores_zero_quality(qtbot):
    controller = _encoder(qtbot)
    controller.apply_profile_to_ui({'codec': 'h265', 'crf': 0, 'encoder_options': {'encoder': 'cpu'}})
    assert controller._ui.widgets.x265_crf.value() == 0
    assert controller._settings.value('encoder/h265/crf') == 0


@pytest.mark.parametrize('option, widget, value', [
    ('preserve_dv', 'preserve_dv_cb', False), ('preserve_hdrplus', 'preserve_hdrplus_cb', False),
    ('autocrop_enabled', 'autocrop_cb', False), ('imax_auto_detect', 'imax_detect_cb', True),
])
def test_profile_restores_feature_policy(qtbot, option, widget, value):
    controller = _encoder(qtbot)
    controller.apply_profile_to_ui({'codec': 'h265', 'encoder_options': {'encoder': 'cpu', option: value}})
    assert getattr(controller._ui.widgets, widget).isChecked() is value
    assert controller.collect_enc_opts()[option] is value


def test_auto_profile_applies_resolved_backend_options(qtbot):
    controller = _encoder(qtbot)
    controller.apply_profile_to_ui({'codec': 'h265', 'encoder_options': {'encoder': 'auto', 'cq': 17, 'preset': 'p7'}})
    assert controller.collect_enc_opts()['cq'] == 17
    assert controller.collect_enc_opts()['preset'] == 'p7'


@pytest.mark.parametrize('option,value', [('quality_target_enabled', True), ('quality_target_vmaf', 97.0),
    ('sdr_hdr_enabled', True), ('sdr_hdr_backend', 'comfyui'), ('autocrop_mode', 'multi'),
    ('hdr10plus_generator_enabled', True), ('comfyui_base_url', 'http://127.0.0.1:8199')])
def test_profile_advanced_options_reach_worker_and_reload(qtbot, option, value):
    controller = _encoder(qtbot)
    profile = {'codec': 'h265', 'encoder_options': {'encoder': 'cpu', option: value}}
    controller.apply_profile_to_ui(profile)
    assert controller.collect_enc_opts()[option] == value
    reloaded = _encoder(qtbot, settings=controller._settings)
    reloaded.load_encoder_settings()
    assert reloaded.collect_enc_opts()[option] == value
    reloaded.reset_to_defaults()
    assert reloaded.collect_enc_opts()[option] != value


def test_profile_scale_mode_and_cpu_option_crf_are_restored(qtbot):
    controller = _encoder(qtbot)
    controller.apply_profile_to_ui({'codec': 'h265', 'scale': '4k',
                                   'encoder_options': {'encoder': 'cpu', 'crf': 0, 'preset': 'slow'}})
    assert controller._ui.widgets.scale_combo.currentText() == '4K (2160p)'
    assert controller._ui.widgets.x265_preset.currentText() == 'slow'
    assert controller._ui.widgets.x265_crf.value() == 0


def test_multi_file_encoder_override_is_deeply_owned():
    from dragontools.gui.convert_widget_encoder_apply import apply_encoder_override
    shared = {'encoder': 'nvenc', 'encoder_options': {'cq': 18}}
    old = {'encoder_profile': {'encoder_options': {'preserve_dv': True}}}
    owner = SimpleNamespace(_state=SimpleNamespace(file_overrides={'a.mkv': old}, thread=None),
                            update_queue_label=lambda p: None)
    apply_encoder_override(owner, ['a.mkv', 'b.mkv'], shared)
    owner._state.file_overrides['a.mkv']['encoder_override']['encoder_options']['cq'] = 40
    owner._state.file_overrides['a.mkv']['encoder_profile']['encoder_options']['preserve_dv'] = False
    assert owner._state.file_overrides['b.mkv']['encoder_override']['encoder_options']['cq'] == 18
    assert shared['encoder_options']['cq'] == 18
    assert old['encoder_profile']['encoder_options']['preserve_dv'] is True


def test_dialog_merge_owns_private_nested_fields():
    from dragontools.gui.convert_widget_override_apply import merge_dialog_override
    old = {'encoder_profile': {'encoder_options': {'cq': 18}}}
    value = merge_dialog_override(old, {'imax': True})
    value['encoder_profile']['encoder_options']['cq'] = 40
    assert old['encoder_profile']['encoder_options']['cq'] == 18


@pytest.mark.parametrize('action', ['_toggle_imax', '_allow_suspicious_source', '_assign_encoder_profile'])
def test_every_override_action_invalidates_preview(monkeypatch, action):
    from dragontools.gui.convert_widget_queue_override_actions import ConvertWidgetQueueOverrideActionsMixin
    from dragontools.gui.convert_widget_source_visual_actions import ConvertWidgetSourceVisualActionsMixin
    class Owner(ConvertWidgetQueueOverrideActionsMixin, ConvertWidgetSourceVisualActionsMixin):
        pass
    owner = Owner()
    owner.default_codec = 'h265'
    owner._state = SimpleNamespace(file_overrides={}, preflight_rows_by_path={'a.mkv': object()}, thread=None)
    owner._controller = SimpleNamespace()
    owner._guard_queue_edit_allowed = lambda a: True
    owner._log = lambda *a: None
    owner.update_queue_label = lambda p: None
    owner._encoder_profile_choices = lambda: [('Profile', {'key': 'custom', 'codec': 'h265'})]
    monkeypatch.setattr('dragontools.gui.convert_widget_queue_override_actions.QInputDialog.getItem',
                        lambda *a, **k: ('Profile', True))
    getattr(owner, action)('a.mkv')
    assert 'a.mkv' not in owner._state.preflight_rows_by_path


@pytest.mark.parametrize('mode', ['take', 'delete', 'native_clear'])
def test_queue_index_recovers_native_item_removal(qtbot, mode):
    from dragontools.gui.convert_widget_file_queue import FileListWidget
    from PyQt6.QtWidgets import QListWidget
    widget = FileListWidget()
    qtbot.addWidget(widget)
    assert widget.add_path('a.mkv')
    if mode == 'native_clear':
        QListWidget.clear(widget)
    else:
        item = widget.takeItem(0)
        if mode == 'delete':
            sip.delete(item)
    assert widget.item_for_path('a.mkv') is None
    assert widget.add_path('a.mkv')
    assert widget.count() == 1


def test_root_directory_cache_preserves_root():
    from dragontools.gui.preflight_metadata_common import MetadataLookupCache
    assert Path('/').is_dir()
    assert MetadataLookupCache().directory_exists('/') is True


def test_move_recovery_facade_accepts_episode_replacement_policy():
    from dragontools.gui.convert_widget import ConvertWidget
    seen = {}
    owner = SimpleNamespace(_recovery_service=SimpleNamespace(restore_job_files=lambda paths, **k: seen.update(k)))
    ConvertWidget.restore_job_files(owner, [], context='move', episode_replacement_mode='replace')
    assert seen['episode_replacement_mode'] == 'replace'


@pytest.mark.parametrize('kind', ['drop', 'filtered_drop'])
def test_locked_drop_cannot_add_unregistered_rows(qtbot, tmp_path, kind):
    from dragontools.gui.convert_widget_queue_dragdrop import ConvertWidgetQueueDragDropMixin
    from dragontools.gui.convert_widget_file_queue import FileListWidget
    class Owner(ConvertWidgetQueueDragDropMixin, QWidget):
        pass
    owner = Owner()
    qtbot.addWidget(owner)
    owner.file_list = FileListWidget(owner)
    admitted = []
    def collect(mime):
        admitted.append(True)
        owner.file_list.add_path('a.mkv')
        return ['a.mkv']
    owner._guard_queue_edit_allowed = lambda action: False
    owner._file_queue = SimpleNamespace(collect_video_paths_from_mime_data=collect)
    owner.add_dropped_files = lambda paths: None
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(tmp_path / 'a.mkv'))])
    event = QDropEvent(QPointF(1, 1), Qt.DropAction.CopyAction, mime,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    if kind == 'drop':
        owner.dropEvent(event)
    else:
        assert owner.eventFilter(owner.file_list, event) is True
    assert owner.file_list.count() == 0
    assert admitted == []
    assert not event.isAccepted()


@pytest.mark.parametrize('method', ['add_files', 'add_folder'])
def test_file_chooser_revalidates_queue_lock(monkeypatch, method):
    from dragontools.gui.convert_widget_queue_add import ConvertWidgetQueueAddMixin
    class Owner(ConvertWidgetQueueAddMixin):
        pass
    owner = Owner()
    available = [True]
    added = []
    owner.guard_queue_edit_allowed = lambda action: available[0]
    owner.parent_widget = None
    owner.file_list = SimpleNamespace(add_path=lambda p: added.append(p) or True)
    owner.state = SimpleNamespace(thread=None)
    owner.log = lambda *a: None
    owner._refresh_labels = lambda *a: None
    owner._sync_total_files = lambda: None
    owner.maybe_preflight_new_files = lambda *a: None
    def choose(*a, **k):
        available[0] = False
        return (['a.mkv'], '') if method == 'add_files' else 'folder'
    name = 'getOpenFileNames' if method == 'add_files' else 'getExistingDirectory'
    monkeypatch.setattr('dragontools.gui.convert_widget_queue_add.QFileDialog.' + name, choose)
    monkeypatch.setattr('dragontools.gui.convert_widget_queue_add._iter_video_files_in_folder',
                        lambda p: (['a.mkv'], 0))
    getattr(owner, method)()
    assert added == []


def test_refreshed_series_choices_replace_previous_resolved_folder(qtbot):
    dialog, widget = _series(qtbot)
    widget.apply_existing_series_dir(r'D:\TV\Example (1990)', r'D:\TV', 'Example')
    widget.apply_existing_series_dir_choices(series_name='Example', choices=[
        {'path': r'D:\TV\Example (2024)', 'base': r'D:\TV', 'base_type': 'TV'}])
    widget._folder_choice_combo.setCurrentIndex(1)
    assert '2024' in next(iter(widget.get_planned_targets().values()))


def test_full_dialog_commit_revalidates_queue_lock(monkeypatch):
    from dragontools.tests.test_patch_bc_multi_file_settings_runtime import _controls
    from dragontools.gui.convert_widget_override_dialog import ConvertWidgetOverrideDialogHelper
    state = SimpleNamespace(file_overrides={'a.mkv': {'imax': False}}, thread=None)
    owner = SimpleNamespace(_guard_queue_edit_allowed=lambda action: False,
                            update_queue_label=lambda p: None, log_message=lambda *a: None, _log=lambda *a: None,
                            default_codec='h265')
    helper = ConvertWidgetOverrideDialogHelper(owner)
    monkeypatch.setattr(helper._encoder_override, 'persist_group', lambda *a: None)
    helper._persist_override_result(['a.mkv'], state, {}, _controls())
    assert state.file_overrides['a.mkv'] == {'imax': False}


def test_start_preparation_blocks_queue_intake_but_live_conversion_allows_it(monkeypatch):
    from dragontools.gui.convert_widget_runtime_ui import ConvertWidgetRuntimeUI
    monkeypatch.setattr('dragontools.gui.convert_widget_runtime_ui.QMessageBox.information', lambda *a: None)
    state = SimpleNamespace(thread=None, move_thread=None, start_reserved=True)
    runtime = ConvertWidgetRuntimeUI(parent_widget=None, state=state, ui=None,
                                    log=lambda *a: None, refresh_queue=lambda: None)
    assert runtime.guard_queue_edit_allowed('add') is False
    state.thread = object()
    assert runtime.guard_queue_edit_allowed('add') is True


def test_watch_intake_waits_for_preflight_snapshot():
    from dragontools.gui.convert_widget_watch_intake import ConvertWidgetWatchMixin
    class Owner(ConvertWidgetWatchMixin):
        pass
    owner = Owner()
    owner._state = SimpleNamespace(start_reserved=True, thread=None)
    owner._is_queue_blocking_move_active = lambda: False
    owner._watch_profile_override = lambda p: pytest.fail('intake passed reservation')
    assert owner.enqueue_watch_folder_files(['a.mkv']) == []


def test_queue_window_native_object_released_on_close(qtbot, monkeypatch):
    from dragontools.gui.convert_queue_window import ConvertQueueWindow
    from dragontools.gui.convert_widget_file_queue import FileListWidget
    monkeypatch.setattr('dragontools.gui.convert_queue_window.save_window_geometry', lambda *a: None)
    monkeypatch.setattr('dragontools.gui.convert_queue_window.restore_window_geometry', lambda *a: None)
    parent = QWidget()
    qtbot.addWidget(parent)
    source = FileListWidget(parent)
    closed = []
    window = ConvertQueueWindow(parent, default_codec='h265', source_list=source,
        is_queue_blocking_move_active=lambda: False, active_worker=lambda: None,
        apply_queue_order=lambda p: None, toggle_pause=lambda: None, abort=lambda: None,
        on_closed=lambda: closed.append(True))
    window.show()
    window.close()
    qtbot.waitUntil(lambda: sip.isdeleted(window))
    assert closed == [True]


@pytest.mark.parametrize('context', ['job', 'move'])
def test_recovery_deeply_owns_restored_settings(qtbot, tmp_path, context):
    from dragontools.gui.convert_widget_recovery import ConvertWidgetRecoveryService
    from dragontools.gui.convert_widget_file_queue import FileListWidget
    from dragontools.gui.conversion_session_state import ConversionSessionState
    file = tmp_path / 'a.mkv'
    file.write_bytes(b'x')
    source = FileListWidget()
    qtbot.addWidget(source)
    state = ConversionSessionState()
    value = {'encoder_profile': {'encoder_options': {'cq': 18}}}
    plan = {'target': 'destination', 'metadata': {'year': 2024}}
    service = ConvertWidgetRecoveryService(state=state, file_list=source, log=lambda *a: None,
        active_worker=lambda: None, refresh_queue=lambda: None, update_label=lambda p: None,
        default_codec='h265', get_subtitle_rules=lambda: {}, overwrite_original=lambda: False,
        get_tools=lambda: None)
    service.restore_job_files([str(file)], context=context,
        file_overrides={str(file): value}, planned_targets={str(file): plan})
    if context == 'job':
        state.file_overrides[str(file)]['encoder_profile']['encoder_options']['cq'] = 40
        assert value['encoder_profile']['encoder_options']['cq'] == 18
    else:
        state.planned_targets[str(file)]['metadata']['year'] = 1990
        assert plan['metadata']['year'] == 2024


@pytest.mark.parametrize('backend, options', [('cpu', {'tune': 'animation', 'aq_mode': '3', 'bf': 7}),
    ('nvenc', {'cq': 16, 'preset': 'p7', 'spatial_aq': False, 'multipass': 'fullres'}),
    ('qsv', {'q': 19, 'preset': 'slow', 'lookahead_depth': 30}), ('amf', {'qp': 19, 'quality': 'quality'})])
def test_profile_backend_roundtrip_positive(qtbot, backend, options):
    controller = _encoder(qtbot)
    controller.apply_profile_to_ui({'codec': 'h265', 'crf': 19, 'preset': 'slow',
                                   'encoder_options': {'encoder': backend, **options}})
    result = controller.collect_enc_opts()
    assert all(result[key] == value for key, value in options.items())
    before = deepcopy(result)
    reloaded = _encoder(qtbot, settings=controller._settings)
    reloaded.load_encoder_settings()
    assert reloaded.collect_enc_opts() == before


@pytest.mark.parametrize('value, expected', [(120.0, 100.0), (50.0, 70.0)])
def test_profile_quality_policy_uses_same_bounds_as_global_settings(qtbot, value, expected):
    controller = _encoder(qtbot)
    controller.apply_profile_to_ui({'codec': 'h265', 'encoder_options': {'quality_target_vmaf': value}})
    assert controller.collect_enc_opts()['quality_target_vmaf'] == expected


@pytest.mark.parametrize('kind', ['series', 'movie'])
@pytest.mark.parametrize('background', [False, True])
def test_selected_metadata_year_reaches_nfo_after_config_and_normalization(qtbot, tmp_path, kind, background):
    from dragontools.gui.conversion_worker_factory import ConversionConfigBuilder
    from dragontools.core.models import normalize_override_dict
    from dragontools.core.online_metadata import parse_series_query, parse_movie_query
    from dragontools.worker.postprocess_runner import PostProcessService
    from dragontools.worker.postprocess_models import NfoSettings
    from dragontools.worker.postprocess_metadata_resolution import MetadataResolution
    from dragontools.worker.job_process_owner import JobProcessOwner
    controller = _encoder(qtbot)
    source = str(tmp_path / ('Example.1990.S01E01.mkv' if kind == 'series' else 'Example.mkv'))
    target = str(tmp_path / 'library' / 'Example (2024)')
    if kind == 'series':
        target = str(Path(target) / 'Staffel 01')
    state = SimpleNamespace(file_overrides={}, planned_targets={source: target})
    builder = ConversionConfigBuilder(state=state, ui=controller._ui.widgets,
        default_codec='h265', collect_encoder_options=controller.collect_enc_opts,
        get_target_paths=lambda: {}, log=lambda *a: None)
    builder.subtitle_rules = lambda: {}
    config = builder.build_converter_config()
    overrides = {p: normalize_override_dict(normalize_override_dict(v)) for p, v in config.file_overrides.items()}
    worker = SimpleNamespace(_job_state=SimpleNamespace(file_overrides=overrides))
    if background:
        worker = JobProcessOwner(worker)
    seen = []
    def resolve(path, **kwargs):
        parsed = (parse_series_query if kind == 'series' else parse_movie_query)(path)
        seen.append((parsed.title, parsed.year))
        return MetadataResolution(SimpleNamespace(), False)
    session = SimpleNamespace(resolve_episode=resolve, resolve_movie=resolve)
    service = PostProcessService(settings=None, tools=None, log=lambda *a: None,
                                 worker=worker, metadata_session=session)
    result = service._resolve_nfo_suggestion(source, NfoSettings(enabled=True))
    assert result[0] == ('episode' if kind == 'series' else 'movie')
    assert seen == [('Example', 2024)]
    assert state.file_overrides == {}


def test_selected_year_survives_result_migration_and_real_move_routing(qtbot, tmp_path, monkeypatch):
    from dragontools.gui.preflight_series_widget import SeriesGroupWidget
    from dragontools.tests.test_conversion_result_service import _service
    from dragontools.core.move_routing import MoveRouter
    base = tmp_path / 'TV'
    source = str(tmp_path / 'Example.1990.S01E01.mkv')
    output = str(tmp_path / 'Example.1990.S01E01_HEVC.mkv')
    widget = SeriesGroupWidget('Example', [{'path': source, 'season': 1, 'year': 1990}], str(base), None, 'TV')
    qtbot.addWidget(widget)
    widget.show()
    widget.apply_existing_series_dir_choices(series_name='Example', choices=[
        {'path': str(base / 'Example (1990)'), 'base': str(base), 'base_type': 'TV'},
        {'path': str(base / 'Example (2024)'), 'base': str(base), 'base_type': 'TV'}])
    widget._folder_choice_combo.setCurrentIndex(2)
    widget.hide()
    service, state, *_ = _service()
    service._set_file_list_item_text = lambda *a: None
    state.planned_targets = widget.get_planned_targets()
    service.on_file_result(source, output, '✅')
    assert source not in state.planned_targets
    planned = state.planned_targets[output]
    assert '2024' in planned
    router = MoveRouter(tv_path=str(base), anime_path='', filme_path='', all_video_files=[output],
        planned_target_for=lambda path: state.planned_targets.get(path),
        ask=lambda p: pytest.fail('authoritative target must not be recalculated'), log=lambda *a: None)
    assert router.route(output) == planned
    assert Path(planned).is_dir()


@pytest.mark.parametrize('entry', ['on_files_dropped', 'add_files', 'add_folder'])
@pytest.mark.parametrize('cancel', [False, True])
def test_live_admission_waits_for_targets_and_cancellation(qtbot, tmp_path, monkeypatch, entry, cancel):
    from dragontools.gui.convert_widget_file_queue import ConvertWidgetFileQueueHelper, FileListWidget
    from dragontools.gui.conversion_session_state import ConversionSessionState
    source = str(tmp_path / 'Example.S01E01.mkv')
    Path(source).write_bytes(b'x')
    target = str(tmp_path / 'TV' / 'Example (2024)' / 'Staffel 01')
    widget = FileListWidget()
    qtbot.addWidget(widget)
    state = ConversionSessionState()
    seen = []
    def add(path, override=None):
        seen.append((path, state.planned_targets.get(path), deepcopy(override)))
        return True
    state.thread = SimpleNamespace(add_file=add, add_file_with_override=add)
    def preflight(paths):
        if cancel:
            for path in paths:
                widget.remove_path(path)
        else:
            state.planned_targets.update({path: target for path in paths})
    helper = ConvertWidgetFileQueueHelper(parent_widget=None, file_list=widget, state=state,
        log=lambda *a: None, guard_queue_edit_allowed=lambda a: True,
        maybe_preflight_new_files=preflight, reset_progress_ui=lambda: None,
        update_label=lambda p: None)
    monkeypatch.setattr('dragontools.gui.convert_widget_queue_add.QFileDialog.getOpenFileNames',
                        lambda *a, **k: ([source], ''))
    monkeypatch.setattr('dragontools.gui.convert_widget_queue_add.QFileDialog.getExistingDirectory',
                        lambda *a, **k: str(tmp_path))
    if entry == 'on_files_dropped':
        widget.add_path(source)
        helper.on_files_dropped([source])
    else:
        getattr(helper, entry)()
    if cancel:
        assert seen == []
    else:
        assert seen[0][1] == target
        assert seen[0][2]['metadata_context']['year'] == 2024


def test_live_watch_admission_waits_for_preflight_year(qtbot, tmp_path):
    from dragontools.gui.convert_widget_watch_intake import ConvertWidgetWatchMixin
    from dragontools.gui.convert_widget_file_queue import FileListWidget
    from dragontools.gui.conversion_session_state import ConversionSessionState
    class Owner(ConvertWidgetWatchMixin):
        pass
    source = str(tmp_path / 'Example.S01E01.mkv')
    owner = Owner()
    owner.file_list = FileListWidget()
    qtbot.addWidget(owner.file_list)
    owner._state = ConversionSessionState()
    target = str(tmp_path / 'TV' / 'Example (2024)' / 'Staffel 01')
    seen = []
    def add(path, override=None):
        seen.append((owner._state.planned_targets.get(path), deepcopy(override)))
        return True
    owner._state.thread = SimpleNamespace(add_file=add, add_file_with_override=add)
    owner._watch_profile_override = lambda p: {}
    owner._is_queue_blocking_move_active = lambda: False
    owner._log = lambda *a: None
    owner.update_queue_label = lambda p: None
    owner._refresh_queue_window = lambda: None
    owner._active_worker = lambda: owner._state.thread
    owner._file_queue = SimpleNamespace(refresh_labels=lambda p: None, sync_total_files=lambda: None,
        sync_queue_order=lambda: None, remove_rejected_from_gui=lambda p: None)
    owner._maybe_preflight_new_files = lambda paths: owner._state.planned_targets.update({p: target for p in paths})
    assert owner.enqueue_watch_folder_files([source]) == [source]
    assert seen[0][0] == target
    assert seen[0][1]['metadata_context']['year'] == 2024


def test_dv_live_admission_owns_override_before_publication(tmp_path):
    from dragontools.worker.dv_remux_thread import DVRemuxThread
    from dragontools.worker.converter_queue_state import ConverterQueueState
    from dragontools.worker.worker_contracts import file_override_for_path
    source = str(tmp_path / 'Example.mkv')
    context = {'kind': 'movie', 'title': 'Example', 'year': 2024}
    owner = SimpleNamespace(_queue=ConverterQueueState([]), file_overrides={}, _log=lambda *a: None)
    class Files(list):
        def append(self, path):
            assert file_override_for_path(owner.file_overrides, path)['metadata_context'] == context
            super().append(path)
    owner._queue.files = Files()
    override = {'metadata_context': deepcopy(context)}
    assert DVRemuxThread.add_file_with_override(owner, source, override) is True
    override['metadata_context']['year'] = 1990
    assert file_override_for_path(owner.file_overrides, source)['metadata_context']['year'] == 2024
    assert DVRemuxThread.add_file_with_override(owner, source, override) is False
    assert file_override_for_path(owner.file_overrides, source)['metadata_context']['year'] == 2024


def test_partial_profile_keeps_other_global_policy_live(qtbot):
    from dragontools.core.settings_conversion import SET_KEY_QUALITY_TARGET_ENABLED, SET_KEY_QUALITY_TARGET_VMAF
    controller = _encoder(qtbot)
    controller.apply_profile_to_ui({'codec': 'h265', 'encoder_options': {'encoder': 'cpu', 'quality_target_vmaf': 97.0}})
    controller._settings.setValue(SET_KEY_QUALITY_TARGET_ENABLED, True)
    controller._settings.setValue(SET_KEY_QUALITY_TARGET_VMAF, 72.0)
    options = controller.collect_enc_opts()
    assert options['quality_target_enabled'] is True
    assert options['quality_target_vmaf'] == 97.0


def test_foreign_codec_profile_and_runtime_capabilities_do_not_change_policy(qtbot):
    controller = _encoder(qtbot)
    before = controller.collect_enc_opts()
    controller.apply_profile_to_ui({'codec': 'av1', 'crf': 0,
                                   'encoder_options': {'encoder': 'nvenc', 'cq': 0}})
    assert controller.collect_enc_opts() == before
    controller.apply_profile_to_ui({'codec': 'h265', 'encoder_options': {'encoder': 'cpu',
        '_comfyui_available': True, 'unknown_future_field': 'ignored'}})
    assert '_comfyui_available' not in controller.collect_enc_opts()
    assert 'unknown_future_field' not in controller.collect_enc_opts()


def test_start_journal_preserves_selected_metadata_year_for_resume(tmp_path, monkeypatch):
    from dragontools.gui.conversion_worker_lifecycle import ConversionWorkerLifecycle
    from dragontools.core.job_journal import JobJournal, build_resume_plan
    source = str(tmp_path / 'Example.S01E01.mkv')
    target = str(tmp_path / 'TV' / 'Example (2024)' / 'Staffel 01')
    Path(source).write_bytes(b'x')
    captured = []
    original_start = JobJournal.start
    def start(**kwargs):
        journal = original_start(**kwargs, root=tmp_path / 'journals')
        captured.append(journal)
        return journal
    monkeypatch.setattr(JobJournal, 'start', start)
    state = SimpleNamespace(file_overrides={}, planned_targets={source: target},
                            job_journal_current_paths=set())
    lifecycle = ConversionWorkerLifecycle(state=state, ui=None, log=lambda *a: None,
        set_start_enabled=lambda v: None, refresh_queue=lambda: None, result_service=None,
        progress_presenter=None, default_codec='h265', collect_encoder_options=lambda: {'encoder': 'cpu'})
    assert lifecycle.start_job_journal(SimpleNamespace(), mode='convert', files=[source]) is True
    plan = build_resume_plan(captured[0].data)
    assert plan['file_overrides'][source]['metadata_context']['year'] == 2024
    assert state.file_overrides == {}
