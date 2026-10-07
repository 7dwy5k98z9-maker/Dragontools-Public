from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
import sqlite3

import pytest

from dragontools.core.media_library_db import _connect, initialize_database, initialize_database_once
from dragontools.core.media_library_item_sql import _insert_item
from dragontools.core.media_library_types import DEFAULT_DB_FILENAME, PathMapping
from dragontools.core.media_library_jellyfin import import_jellyfin_database
from dragontools.core.media_library_scan import scan_storage_paths_to_database
from dragontools.core.media_library_search import search_library
from dragontools.tests.test_review20_media_library_safety import _item
from dragontools.tests.test_media_library import _create_minimal_jellyfin_db, _fake_media_info


def add_item(db, path, title='Keep', **fields):
    item = _item(str(path), title)
    item.update(fields)
    with closing(_connect(db)) as conn, conn:
        return _insert_item(conn, item, [])


def test_configured_offline_root_reaches_rebuild_guard(tmp_path, monkeypatch):
    from dragontools.gui import media_library_dialog_service as module
    from dragontools.core.settings_storage import SET_KEY_PATH_H265_FILME, SET_KEY_PATH_AV1_FILME
    good = tmp_path / 'Filme'
    good.mkdir()
    bad = tmp_path / 'offline'
    values = {SET_KEY_PATH_H265_FILME: str(good), SET_KEY_PATH_AV1_FILME: str(bad)}
    settings = SimpleNamespace(value=lambda key, default='', **kw: values.get(key, default))
    monkeypatch.setattr(module, 'default_target_path_for_settings_key', lambda *a, **kw: '')
    db = initialize_database(tmp_path / 'library.db')
    add_item(db, tmp_path / 'Keep.mkv')
    roots = module.MediaLibraryDialogService().storage_scan_roots(settings)
    assert {root.local_prefix for root in roots} == {str(good), str(bad)}
    result = scan_storage_paths_to_database(db, roots, analyzer=_fake_media_info)
    assert result.aborted
    assert [row['title'] for row in search_library(db)] == ['Keep']


def test_initialize_once_reinitializes_deleted_database(tmp_path):
    db = initialize_database_once(tmp_path / 'library.db')
    db.unlink()
    initialize_database_once(db)
    with closing(_connect(db)) as conn:
        assert conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()


def test_import_rejects_source_target_alias_without_mutating_source(tmp_path):
    source = tmp_path / 'jellyfin.db'
    _create_minimal_jellyfin_db(source)
    before = source.read_bytes()
    with pytest.raises(ValueError, match='(?i)(quelle|source|jellyfin)'):
        import_jellyfin_database(source, source)
    assert source.read_bytes() == before


def test_import_source_basename_cannot_collide_with_working_database(tmp_path):
    source = tmp_path / DEFAULT_DB_FILENAME
    _create_minimal_jellyfin_db(source)
    before = source.read_bytes()
    target = tmp_path / 'target.db'
    result = import_jellyfin_database(source, target)
    assert result.imported_items == 2
    with closing(_connect(target)) as conn:
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='TypedBaseItems'").fetchone() is None
    assert source.read_bytes() == before


def test_import_with_local_analysis_preserves_provider_identity(tmp_path, monkeypatch):
    from dragontools.core import media_analyzer
    source = tmp_path / 'jellyfin.db'
    _create_minimal_jellyfin_db(source)
    root = tmp_path / 'Filme'
    video = root / 'B' / 'Beispiel Film (2026)' / 'Beispiel Film (2026).mkv'
    video.parent.mkdir(parents=True)
    video.write_bytes(b'video')
    monkeypatch.setattr(media_analyzer, 'analyze_media', _fake_media_info)
    target = tmp_path / 'target.db'
    import_jellyfin_database(source, target, [PathMapping('Filme', '/Filme', str(root))], analyze_existing_files=True)
    with closing(_connect(target)) as conn:
        row = conn.execute('SELECT source_id, title, year FROM media_items').fetchone()
    assert tuple(row) == ('movie-1', 'Beispiel Film', 2026)


@pytest.mark.parametrize('profile', ['High', 'Main 10', '0'])
def test_codec_profile_is_not_dolby_vision(tmp_path, profile):
    source = tmp_path / 'jellyfin.db'
    with sqlite3.connect(source) as conn:
        conn.execute('CREATE TABLE BaseItems(Id TEXT, Type TEXT, Name TEXT, Path TEXT)')
        conn.execute("INSERT INTO BaseItems VALUES('m', 'Movie', 'SDR', '/Filme/SDR.mkv')")
        conn.execute('CREATE TABLE MediaStreamInfos(ItemId TEXT, StreamType INTEGER, Codec TEXT, Profile TEXT, ColorTransfer TEXT)')
        conn.execute("INSERT INTO MediaStreamInfos VALUES('m', 1, 'h264', ?, 'bt709')", (profile,))
    target = tmp_path / 'target.db'
    import_jellyfin_database(source, target)
    assert search_library(target, 'dv') == []
    assert [row['title'] for row in search_library(target, 'sdr')] == ['SDR']


def test_vobsub_pair_is_one_external_subtitle(tmp_path):
    from dragontools.core.media_library_sidecars import _subtitle_sidecar_streams
    video = tmp_path / 'Film.mkv'
    video.write_bytes(b'video')
    video.with_suffix('.de.idx').write_bytes(b'index')
    video.with_suffix('.de.sub').write_bytes(b'payload')
    rows = _subtitle_sidecar_streams(video)
    assert len(rows) == 1
    assert rows[0]['external_path'].endswith('.idx')


def test_probe_external_subtitle_is_not_added_twice(tmp_path):
    from dragontools.core.media_library_media_info_mapper import _streams_from_media_info_with_sidecars
    from dragontools.core.models import SubtitleStream
    video = tmp_path / 'Film.mkv'
    video.write_bytes(b'video')
    sidecar = video.with_suffix('.de.srt')
    sidecar.write_text('subtitle', encoding='utf-8')
    info = _fake_media_info(str(video))
    info.subtitle_streams.append(SubtitleStream(index=3, language='deu', forced=False, title='Deutsch', codec='subrip', source_kind='external', external_path=str(sidecar)))
    rows = _streams_from_media_info_with_sidecars(video, info)
    assert len([row for row in rows if row['source_kind'] == 'external']) == 1


@pytest.mark.parametrize('name', ['TV_A', 'TV%'])
def test_scope_prefix_treats_sql_wildcards_literally(tmp_path, name):
    from dragontools.core.media_library_path_mappings import save_path_mappings
    db = initialize_database(tmp_path / 'library.db')
    exact = tmp_path / name
    other = tmp_path / name.replace('_', 'X').replace('%', 'Other')
    add_item(db, exact / 'A.mkv', 'Exact', item_type='episode')
    add_item(db, other / 'B.mkv', 'Other', item_type='episode')
    save_path_mappings(db, [PathMapping('TV', '/TV', str(exact))])
    assert [row['title'] for row in search_library(db, scope='tv')] == ['Exact']


def test_symbol_only_text_search_does_not_match_every_normalized_title(tmp_path):
    db = initialize_database(tmp_path / 'library.db')
    add_item(db, tmp_path / 'A.mkv', 'Contains +')
    add_item(db, tmp_path / 'B.mkv', 'Unrelated')
    assert [row['title'] for row in search_library(db, text='+')] == ['Contains +']


def test_abort_during_final_analysis_prevents_publication(tmp_path):
    root = tmp_path / 'Filme'
    root.mkdir()
    (root / 'New.mkv').write_bytes(b'video')
    db = initialize_database(tmp_path / 'library.db')
    add_item(db, tmp_path / 'Keep.mkv')
    aborted = False
    def analyzer(path, tools):
        nonlocal aborted
        aborted = True
        return _fake_media_info(path)
    result = scan_storage_paths_to_database(db, [PathMapping('Filme', '/Filme', str(root))], analyzer=analyzer, should_abort=lambda: aborted)
    assert result.aborted
    assert [row['title'] for row in search_library(db)] == ['Keep']


def test_database_commit_error_is_not_analyzer_fallback(tmp_path, monkeypatch):
    from dragontools.core import media_library_scan as module
    root = tmp_path / 'Filme'
    root.mkdir()
    (root / 'New.mkv').write_bytes(b'video')
    db = initialize_database(tmp_path / 'library.db')
    add_item(db, tmp_path / 'Keep.mkv')
    original = module._insert_item
    def fail_only_analyzed(conn, item, streams):
        if item['analysis_status'] == 'ok':
            raise sqlite3.OperationalError('synthetic write failure')
        return original(conn, item, streams)
    monkeypatch.setattr(module, '_insert_item', fail_only_analyzed)
    with pytest.raises(sqlite3.OperationalError, match='synthetic write failure'):
        module.scan_storage_paths_to_database(db, [PathMapping('Filme', '/Filme', str(root))], analyzer=_fake_media_info)
    assert [row['title'] for row in search_library(db)] == ['Keep']


def test_empty_root_selection_does_not_erase_library(tmp_path):
    db = initialize_database(tmp_path / 'library.db')
    add_item(db, tmp_path / 'Keep.mkv')
    result = scan_storage_paths_to_database(db, [])
    assert result.aborted
    assert [row['title'] for row in search_library(db)] == ['Keep']


@pytest.mark.parametrize('mutation', ['deactivate', 'delete', 'move'])
def test_nfo_commit_does_not_publish_result_for_stale_database_row(tmp_path, monkeypatch, mutation):
    from dragontools.core import media_library_nfo_scan as module
    video = tmp_path / 'Film.mkv'
    video.write_bytes(b'video')
    video.with_suffix('.nfo').write_text('<movie><title>Old</title></movie>', encoding='utf-8')
    db = initialize_database(tmp_path / 'library.db')
    media_id = add_item(db, video, 'Old')
    original = module._inspect_nfo_candidate
    def mutate(row):
        result = original(row)
        with closing(_connect(db)) as conn, conn:
            if mutation == 'delete':
                conn.execute('DELETE FROM media_items WHERE id=?', (media_id,))
            elif mutation == 'deactivate':
                conn.execute('UPDATE media_items SET active=0 WHERE id=?', (media_id,))
            else:
                conn.execute("UPDATE media_items SET path=?, title='New' WHERE id=?", (str(tmp_path / 'New.mkv'), media_id))
        return result
    monkeypatch.setattr(module, '_inspect_nfo_candidate', mutate)
    module.scan_nfo_inventory(db, backup=False)
    with closing(_connect(db)) as conn:
        assert conn.execute('SELECT * FROM nfo_metadata WHERE media_id=?', (media_id,)).fetchone() is None


def test_reanalysis_preserves_imported_metadata_and_resets_nfo_audit(tmp_path, monkeypatch):
    from dragontools.core import media_analyzer
    from dragontools.core.media_library_repository_items import record_media_file
    video = tmp_path / 'File.mkv'
    video.write_bytes(b'video')
    db = initialize_database(tmp_path / 'library.db')
    media_id = add_item(db, video, 'Canonical', source='jellyfin', source_id='provider-1', year=2020, original_title='Original', nfo_path=str(video.with_suffix('.nfo')), nfo_type='movie', nfo_mtime=123.0, nfo_scanned_at='old')
    monkeypatch.setattr(media_analyzer, 'analyze_media', _fake_media_info)
    record_media_file(db, video)
    with closing(_connect(db)) as conn:
        row = conn.execute('SELECT source_id, title, original_title, year, nfo_scanned_at FROM media_items WHERE id=?', (media_id,)).fetchone()
    assert tuple(row[:4]) == ('provider-1', 'Canonical', 'Original', 2020)
    assert row['nfo_scanned_at'] is None


@pytest.mark.parametrize('operation', ['import', 'scan'])
def test_rebuild_publishes_consistently_to_open_wal_database(tmp_path, operation):
    db = initialize_database(tmp_path / 'library.db')
    add_item(db, tmp_path / 'Old.mkv', 'Old')
    with closing(_connect(db)) as observer:
        observer.execute('PRAGMA wal_autocheckpoint=0')
        observer.execute("UPDATE media_items SET title='Old in WAL'")
        observer.commit()
        assert Path(str(db) + '-wal').stat().st_size > 0
        if operation == 'import':
            source = tmp_path / 'jellyfin.db'
            _create_minimal_jellyfin_db(source)
            import_jellyfin_database(source, db)
            expected = {'Beispiel Film', 'Wegweisende Originalitaet'}
        else:
            root = tmp_path / 'Filme'
            root.mkdir()
            (root / 'New.mkv').write_bytes(b'video')
            result = scan_storage_paths_to_database(db, [PathMapping('Filme', '/Filme', str(root))], analyzer=_fake_media_info)
            assert not result.aborted
            expected = {'New'}
        assert {row[0] for row in observer.execute('SELECT title FROM media_items')} == expected
        assert observer.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert {row['title'] for row in search_library(db)} == expected


def test_successful_analysis_of_disappeared_file_cannot_publish_rebuild(tmp_path):
    db = initialize_database(tmp_path / 'library.db')
    add_item(db, tmp_path / 'Keep.mkv')
    root = tmp_path / 'Filme'
    root.mkdir()
    (root / 'New.mkv').write_bytes(b'video')
    def analyzer(path, tools):
        info = _fake_media_info(path)
        Path(path).unlink()
        return info
    result = scan_storage_paths_to_database(db, [PathMapping('Filme', '/Filme', str(root))], analyzer=analyzer)
    assert result.aborted
    assert [row['title'] for row in search_library(db)] == ['Keep']


def test_search_owns_thread_until_finished_callback_and_exports_original_database(tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QApplication
    from dragontools.gui import media_library_search_controller as module
    app = QApplication.instance() or QApplication([])
    class Signal:
        def __init__(self): self.callbacks = []
        def connect(self, callback): self.callbacks.append(callback)
        def emit(self, *args):
            for callback in self.callbacks: callback(*args)
    class Thread:
        created = []
        def __init__(self, **kw):
            self.kw = kw
            self.running = False
            self.completed, self.finished = Signal(), Signal()
            self.created.append(self)
        def start(self): self.running = True
        def isRunning(self): return self.running
        def deleteLater(self): pass
    monkeypatch.setattr(module, 'MediaLibrarySearchThread', Thread)
    label = SimpleNamespace(setText=lambda value: None)
    view = SimpleNamespace(search_result_label=label, search_option_combo=SimpleNamespace(currentData=lambda: 'all'), search_text_edit=SimpleNamespace(text=lambda: ''), search_scope_combo=SimpleNamespace(currentData=lambda: 'all'), search_type_combo=SimpleNamespace(currentData=lambda: 'all'))
    current_db = 'first.db'
    service = SimpleNamespace(export_search_csv=lambda db, *a, **kw: (Path('result.csv'), exported.append(db) or 1))
    exported = []
    controller = module.MediaLibrarySearchController(parent=None, view=view, service=service, presenter=None, get_db_path=lambda: current_db, refresh_stats=lambda: None)
    controller._render_search_rows = lambda *a: None
    controller.run_search()
    first = Thread.created[0]
    first.running = False
    first.completed.emit(first.kw['request'], [{'title': 'First'}], None)
    current_db = 'second.db'
    monkeypatch.setattr(module.QFileDialog, 'getSaveFileName', lambda *a: ('result.csv', ''))
    monkeypatch.setattr(module.QMessageBox, 'information', lambda *a: None)
    controller.export_search_csv()
    assert exported == ['first.db']
    controller.run_search()
    assert len(Thread.created) == 1
    first.finished.emit()
    assert len(Thread.created) == 2
    assert controller._search_thread is Thread.created[1]
    second = Thread.created[1]
    second.running = False
    second.finished.emit()
    app.processEvents()


def test_dialog_reject_cannot_bypass_active_task_close_guard(monkeypatch):
    from PyQt6.QtWidgets import QApplication
    from dragontools.gui.media_library_dialog import MediaLibraryDialog
    app = QApplication.instance() or QApplication([])
    dialog = MediaLibraryDialog.__new__(MediaLibraryDialog)
    from PyQt6.QtWidgets import QDialog, QMessageBox
    QDialog.__init__(dialog)
    dialog._scan = SimpleNamespace(is_running=True)
    dialog._nfo = SimpleNamespace(is_running=False)
    dialog._fix = SimpleNamespace(is_running=False)
    monkeypatch.setattr(QMessageBox, 'information', lambda *a: None)
    dialog.show()
    dialog.reject()
    assert dialog.isVisible()
    dialog.hide()
    dialog.deleteLater()
    app.processEvents()


def test_incremental_analysis_does_not_lock_out_or_erase_concurrent_writer(tmp_path):
    db = initialize_database(tmp_path / 'library.db')
    root = tmp_path / 'Filme'
    root.mkdir()
    (root / 'New.mkv').write_bytes(b'video')
    writes = []
    def analyzer(path, tools):
        with closing(sqlite3.connect(db, timeout=0)) as conn, conn:
            try:
                conn.execute("INSERT INTO meta(key,value) VALUES('concurrent','keep')")
            except sqlite3.OperationalError:
                writes.append(False)
            else:
                writes.append(True)
        return _fake_media_info(path)
    result = scan_storage_paths_to_database(db, [PathMapping('Filme', '/Filme', str(root))],
                                            replace_existing=False, analyzer=analyzer)
    assert writes == [True]
    assert not result.aborted
    with closing(_connect(db)) as conn:
        assert conn.execute("SELECT value FROM meta WHERE key='concurrent'").fetchone()[0] == 'keep'


@pytest.mark.parametrize('profile', ['0', 'High', 'Main 10', '0.8', '8abc', '8.1.2', '8.', '.8'])
def test_cached_non_dv_stream_profile_is_not_positive_search_evidence(tmp_path, profile):
    from dragontools.core.media_library_media_info_mapper import _streams_from_media_info
    db = initialize_database(tmp_path / 'library.db')
    video = tmp_path / 'Video.mkv'
    streams = _streams_from_media_info(_fake_media_info(str(video)))
    streams[0].update(dv_profile=profile, hdr_format='SDR')
    with closing(_connect(db)) as conn, conn:
        _insert_item(conn, _item(str(video), 'Video'), streams)
    assert search_library(db, preset='dv') == []
    rows = search_library(db)
    assert rows[0]['has_dolby_vision'] == 0
    assert rows[0]['is_hdr'] == 0


@pytest.mark.parametrize('profile,format_value', [('8', 'SDR'), ('8.1', 'SDR'), ('08', 'SDR'), (None, 'Dvh1'), (None, 'dav1')])
def test_dv_search_and_display_agree_on_positive_evidence(tmp_path, profile, format_value):
    from dragontools.core.media_library_media_info_mapper import _streams_from_media_info
    db = initialize_database(tmp_path / 'library.db')
    video = tmp_path / 'Video.mkv'
    streams = _streams_from_media_info(_fake_media_info(str(video)))
    streams[0].update(dv_profile=profile, hdr_format=format_value)
    with closing(_connect(db)) as conn, conn:
        _insert_item(conn, _item(str(video), 'Video'), streams)
    rows = search_library(db, preset='dv')
    assert len(rows) == 1
    assert rows[0]['has_dolby_vision'] == 1
    assert rows[0]['is_hdr'] == 1
    assert len(search_library(db, preset='hdr')) == 1


@pytest.mark.parametrize('action', ['close', 'reject', 'accept'])
def test_native_dialog_all_completion_paths_save_once(monkeypatch, action):
    from PyQt6.QtWidgets import QApplication, QDialog
    from dragontools.gui import media_library_dialog as module
    app = QApplication.instance() or QApplication([])
    dialog = module.MediaLibraryDialog.__new__(module.MediaLibraryDialog)
    QDialog.__init__(dialog)
    dialog._scan = dialog._nfo = dialog._fix = SimpleNamespace(is_running=False)
    dialog._search = SimpleNamespace(shutdown=lambda: True)
    dialog.settings = None
    saves = []
    dialog._save_without_popup = lambda: saves.append('save')
    monkeypatch.setattr(module, 'save_window_geometry', lambda *a: None)
    dialog.show()
    getattr(dialog, action)()
    assert not dialog.isVisible()
    assert saves == ['save']
    dialog.deleteLater()
    app.processEvents()


def test_native_dialog_accept_cannot_bypass_running_task(monkeypatch):
    from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox
    from dragontools.gui.media_library_dialog import MediaLibraryDialog
    app = QApplication.instance() or QApplication([])
    dialog = MediaLibraryDialog.__new__(MediaLibraryDialog)
    QDialog.__init__(dialog)
    dialog._scan = SimpleNamespace(is_running=True)
    dialog._nfo = dialog._fix = SimpleNamespace(is_running=False)
    monkeypatch.setattr(QMessageBox, 'information', lambda *a: None)
    dialog.show()
    dialog.accept()
    assert dialog.isVisible()
    dialog.hide()
    dialog.deleteLater()
    app.processEvents()


def test_rebuild_rechecks_earlier_source_after_later_analysis(tmp_path):
    db = initialize_database(tmp_path / 'library.db')
    add_item(db, tmp_path / 'Keep.mkv')
    root = tmp_path / 'Filme'
    root.mkdir()
    first, second = root / 'A.mkv', root / 'B.mkv'
    first.write_bytes(b'first')
    second.write_bytes(b'second')
    def analyzer(path, tools):
        if Path(path) == second:
            first.write_bytes(b'changed first video')
        return _fake_media_info(path)
    result = scan_storage_paths_to_database(db, [PathMapping('Filme', '/Filme', str(root))], analyzer=analyzer)
    assert result.aborted
    assert [row['title'] for row in search_library(db)] == ['Keep']
