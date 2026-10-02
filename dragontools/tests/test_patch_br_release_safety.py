from __future__ import annotations

import errno
import os
import subprocess
from pathlib import Path

import pytest

from dragontools.tests.test_settings_backup import FakeSettings


def test_restore_checks_qsettings_status_and_rolls_back_files(tmp_path):
    from PyQt6.QtCore import QSettings
    from dragontools.core.settings_backup import export_backup, restore_backup

    class FailingStatus(FakeSettings):
        def status(self):
            return QSettings.Status.AccessError

    docs = tmp_path / 'docs'
    (docs / 'rules').mkdir(parents=True)
    rule = docs / 'rules' / 'audio_rules.json'
    rule.write_bytes(b'new')
    archive = tmp_path / 'backup.zip'
    export_backup(archive, settings=FakeSettings({'new': 2}), documents_dir=docs)
    rule.write_bytes(b'old')
    settings = FailingStatus({'old': 1})
    with pytest.raises(OSError, match='gespeichert'):
        restore_backup(archive, settings=settings, documents_dir=docs)
    assert settings.values == {'old': 1}
    assert rule.read_bytes() == b'old'


def test_real_qsettings_sync_failure_is_detected(tmp_path):
    from PyQt6.QtCore import QSettings
    from dragontools.core.settings_backup_restore import sync_settings_checked
    # A file cannot be used as the parent directory of an INI file.
    parent = tmp_path / 'not_a_directory'
    parent.write_bytes(b'block')
    settings = QSettings(str(parent / 'settings.ini'), QSettings.Format.IniFormat)
    settings.setValue('key', 'value')
    with pytest.raises(OSError, match='gespeichert'):
        sync_settings_checked(settings)
    assert settings.status() == QSettings.Status.AccessError


def test_real_qsettings_restore_success(tmp_path):
    from PyQt6.QtCore import QSettings
    from dragontools.core.settings_backup import export_backup, restore_backup
    settings = QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat)
    settings.setValue('old', 1)
    archive = tmp_path / 'backup.zip'
    export_backup(archive, settings=FakeSettings({'new': 2}), documents_dir=tmp_path / 'docs')
    restore_backup(archive, settings=settings, documents_dir=tmp_path / 'docs')
    assert settings.status() == QSettings.Status.NoError
    assert settings.value('new', type=int) == 2
    assert not settings.contains('old')


def test_backup_fsync_failure_preserves_old_archive(tmp_path, monkeypatch):
    import dragontools.core.settings_backup_export as module
    archive = tmp_path / 'backup.zip'
    archive.write_bytes(b'old')
    def fail(*_):
        raise OSError(errno.ENOSPC, 'disk full')
    monkeypatch.setattr(module.os, 'fsync', fail)
    with pytest.raises(OSError):
        module.export_backup(archive, settings=FakeSettings(), documents_dir=tmp_path / 'docs')
    assert archive.read_bytes() == b'old'
    assert not list(tmp_path.glob('*.tmp'))


def test_corrupt_directory_stage_never_replaces_old_destination(tmp_path, monkeypatch):
    import dragontools.core.move_transaction as module
    source, destination = tmp_path / 'source', tmp_path / 'dest'
    source.mkdir(); destination.mkdir()
    (source / 'file').write_bytes(b'correct')
    (destination / 'old').write_bytes(b'original')
    real_copy = module.copy_path_to_staging
    def corrupt(src, stage):
        real_copy(src, stage)
        (stage / 'file').write_bytes(b'corrupt')
    monkeypatch.setattr(module, 'copy_path_to_staging', corrupt)
    transaction = module.PathSwapTransaction(source, destination, tmp_path / 'backup')
    with pytest.raises(OSError, match='Integritätsprüfung'):
        transaction.stage()
    assert (source / 'file').read_bytes() == b'correct'
    assert (destination / 'old').read_bytes() == b'original'
    assert not list(tmp_path.glob('*.__dragontools_partial__*'))


def test_worker_snapshot_is_detached_and_read_only():
    from dragontools.core.settings_access import worker_settings_snapshot
    settings = FakeSettings({'list': [1], 'enabled': 'false'})
    snapshot = worker_settings_snapshot(settings)
    settings.values['list'].append(2)
    snapshot.value('list').append(3)
    assert snapshot.value('list') == [1]
    assert snapshot.value('enabled', True, type=bool) is False
    assert snapshot.contains('list')
    assert not hasattr(snapshot, 'setValue')


def test_actual_journal_write_failure_rolls_back_after_install(tmp_path, monkeypatch):
    from dragontools.core.output_replace import commit_staged_output
    import dragontools.core.replace_journal as journal
    source, staged = tmp_path / 'source', tmp_path / 'staged'
    source.write_bytes(b'old'); staged.write_bytes(b'new')
    write = journal.atomic_write_json
    def fail(path, data):
        if data.get('status') == 'committed':
            raise OSError(errno.ENOSPC, 'journal disk full')
        return write(path, data)
    monkeypatch.setattr(journal, 'atomic_write_json', fail)
    with pytest.raises(journal.ReplaceJournalWriteError):
        commit_staged_output(source=source, staging=staged, destination=source,
                             log=lambda *_: None, journal_root=tmp_path / 'journals')
    assert source.read_bytes() == b'old'
    assert staged.read_bytes() == b'new'


def test_cross_volume_directory_success_verifies_before_source_removal(tmp_path, monkeypatch):
    import dragontools.core.move_transfer_executor as module
    from dragontools.core.move_file_service import MoveFileService
    source, target = tmp_path / 'source', tmp_path / 'target'
    source.mkdir(); target.mkdir()
    (source / 'file').write_bytes(b'full content')
    def cross_volume(*_args):
        raise OSError(errno.EXDEV, 'different volumes')
    monkeypatch.setattr(module.os, 'rename', cross_volume)
    service = MoveFileService(conflict_mode='skip', log=lambda *_: None,
                              wait=lambda: None, abort_immediately=lambda: False, journal=None)
    assert service.move(str(source), str(target))
    assert not source.exists()
    assert (target / 'source' / 'file').read_bytes() == b'full content'


@pytest.mark.skipif(os.name != 'nt', reason='Windows batch rollback')
@pytest.mark.parametrize('have_current', [False, True])
def test_actual_build_backup_blocks_restore_legacy_on_failure(tmp_path, have_current):
    root = Path(__file__).resolve().parents[2]
    script = (root / 'build_v9.bat').read_text(encoding='utf-8')
    backup = script.split('set "LEGACY_DIST_ROOT=')[1].split('REM Alte Test-/Bytecode-Artefakte')[0]
    backup = 'set "LEGACY_DIST_ROOT=' + backup
    rollback = script.split('\n:BUILD_FAILED\n')[1].split('set "BUILD_RC=1"')[0]
    legacy = tmp_path / 'dist' / 'DragonToolsV9'
    legacy.mkdir(parents=True)
    (legacy / 'keep').write_bytes(b'legacy')
    current = tmp_path / 'dist' / 'DragonToolsV9.8.7'
    if have_current:
        current.mkdir(); (current / 'keep').write_bytes(b'current')
    harness = tmp_path / 'rollback.bat'
    harness.write_text('@echo off\nsetlocal\nset "BACKUP_CREATED="\n'
                       'set "DIST_ROOT=dist\\DragonToolsV9.8.7"\n'
                       'set "BACKUP_DIST_ROOT=%DIST_ROOT%.__previous__"\n'
                       + backup + '\ngoto :BUILD_FAILED\n:BUILD_FAILED\n' + rollback
                       + '\nexit /b 0\n', encoding='utf-8')
    subprocess.run(['cmd', '/c', str(harness)], cwd=tmp_path, check=True,
                   capture_output=True, timeout=15)
    assert (legacy / 'keep').read_bytes() == b'legacy'
    if have_current:
        assert (current / 'keep').read_bytes() == b'current'
    assert not list((tmp_path / 'dist').glob('*.__previous__'))
