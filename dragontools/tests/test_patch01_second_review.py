from __future__ import annotations

import json
import os
from types import SimpleNamespace
import zipfile

import pytest


@pytest.mark.parametrize('seconds',[61,90,36001])
def test_timeout_dialog_preserves_untouched_seconds(qtbot,monkeypatch,seconds):
    from dragontools.gui import timeout_settings_dialog as module
    monkeypatch.setattr(module,'get_timeout_value',lambda key:seconds)
    monkeypatch.setattr(module,'is_timeout_enabled',lambda key:True)
    monkeypatch.setattr(module,'install_persistent_window_geometry',lambda *a,**k:None)
    saved=[]
    monkeypatch.setattr(module,'save_all_timeouts',lambda values,enabled:saved.append(dict(values)))
    dialog=module.TimeoutSettingsDialog()
    qtbot.addWidget(dialog)
    dialog._save_and_accept()
    assert saved and all(value==seconds for value in saved[0].values())


def test_live_tool_preview_does_not_mutate_process_search_path(tmp_path,monkeypatch):
    from dragontools.gui.tool_path_live_check import _CurrentToolPathProvider,_tool_props
    from dragontools.core.settings_storage import TOOL_KEYS
    preview=tmp_path/'unsaved-tools'
    preview.mkdir()
    (preview/'ffmpeg.exe').write_bytes(b'not-executed')
    before=os.environ.get('PATH','')
    monkeypatch.setenv('PATH',before)
    props=_tool_props(_CurrentToolPathProvider({TOOL_KEYS['ffmpeg'][1]:str(preview)}))
    assert props['ffmpeg']==str(preview/'ffmpeg.exe')
    assert os.environ['PATH']==before


def test_failed_ffmpeg_capability_queries_do_not_advertise_error_keywords(monkeypatch):
    from dragontools.core import tool_diagnostics as module
    monkeypatch.setattr(module,'_run_tool',lambda *a,**k:(1,'Unavailable: libplacebo hevc_nvenc libx265 libsvtav1 -multipass -lookahead_level dolbyvision'))
    assert module._probe_ffmpeg_features('ffmpeg.exe')==[]


@pytest.mark.parametrize('content',[b'{broken',b'[]',b'null'])
def test_restore_rejects_invalid_configuration_before_writes(tmp_path,content):
    from dragontools.core.settings_backup import restore_backup
    from dragontools.tests.test_review01_settings_transaction import FakeSettings
    root=tmp_path/'restore'
    (root/'rules').mkdir(parents=True)
    target=root/'rules/audio_rules.json'
    target.write_bytes(b'{"keep":true}')
    archive=tmp_path/'backup.zip'
    with zipfile.ZipFile(archive,'w') as zf:
        zf.writestr('manifest.json',json.dumps({'format':'DragonToolsBackup','format_version':2,'secrets':{'mode':'excluded'}}))
        zf.writestr('settings.json','{"normal":"new"}')
        zf.writestr('files/rules/audio_rules.json',content)
    settings=FakeSettings({'normal':'old'})
    with pytest.raises(ValueError):
        restore_backup(archive,settings=settings,documents_dir=root)
    assert settings.values=={'normal':'old'}
    assert settings.synced==0
    assert target.read_bytes()==b'{"keep":true}'


def test_logging_only_section_does_not_commit_hidden_target_paths(tmp_path,monkeypatch):
    from dragontools.gui.settings_sections import storage
    from dragontools.core import settings as cfg
    from dragontools.tests.test_review01_settings_transaction import FakeSettings
    settings=FakeSettings({cfg.SET_KEY_PATH_H265_TV:'previous-target'})
    checkbox=SimpleNamespace(isChecked=lambda:True)
    edit=SimpleNamespace(text=lambda:str(tmp_path/'should-not-be-created'))
    dialog=SimpleNamespace(settings=settings,_visible_sections=('logging',),
        _path_edits={cfg.SET_KEY_PATH_H265_TV:edit},cb_tv=checkbox,cb_anime=checkbox,cb_filme=checkbox,
        _log_cbs={cfg.SET_KEY_LOG_ENABLED:checkbox},_log_edits={cfg.SET_KEY_LOG_ROOT:edit})
    assert storage.StorageLoggingSection(dialog).save() is True
    assert settings.values[cfg.SET_KEY_PATH_H265_TV]=='previous-target'
    assert not (tmp_path/'should-not-be-created').exists()


def test_timeout_edit_and_reset_keep_exact_default(qtbot,monkeypatch):
    from dragontools.gui import timeout_settings_dialog as module
    monkeypatch.setattr(module,'get_timeout_value',lambda key:61)
    monkeypatch.setattr(module,'is_timeout_enabled',lambda key:False)
    monkeypatch.setattr(module,'install_persistent_window_geometry',lambda *a,**k:None)
    dialog=module.TimeoutSettingsDialog()
    qtbot.addWidget(dialog)
    key='format_detection'
    dialog._spinboxes[key].setValue(3)
    assert dialog._timeout_seconds[key]==180
    dialog._reset_timeout(key)
    assert dialog._timeout_seconds[key]==90
    assert dialog._enabled_cbs[key].isChecked()


@pytest.mark.parametrize('visible',['logging','defaults','containers','save','media_library','watch_folders','sdr_hdr'])
def test_real_focused_dialog_preserves_hidden_group_values(qtbot,tmp_path,monkeypatch,visible):
    from PyQt6.QtCore import QSettings
    from dragontools.gui import settings_dialog
    from dragontools.gui.settings_sections import storage
    from dragontools.core import settings as cfg
    settings=QSettings(str(tmp_path/'settings.ini'),QSettings.Format.IniFormat)
    sentinels={
        cfg.SET_KEY_PATH_H265_TV:('paths','previous-uncreated-target'),
        cfg.SET_KEY_PARALLEL_CPU_JOBS:('parallel',99),
        cfg.SET_KEY_OUTPUT_DURATION_MIN_PERCENT:('validation',0),
        cfg.SET_KEY_IMAX_PROBE_INTERVAL:('imax',1),
        cfg.SET_KEY_NFO_TIMING:('postprocess','unknown-timing'),
        cfg.SET_KEY_WATCH_RULES:('watch_folders','malformed-watch-rules'),
    }
    for key,(_group,value) in sentinels.items():settings.setValue(key,value)
    monkeypatch.setattr(settings_dialog,'QSettings',lambda *a:settings)
    monkeypatch.setattr(settings_dialog,'install_persistent_window_geometry',lambda *a,**k:None)
    monkeypatch.setattr(settings_dialog,'log_qsettings_changes',lambda *a,**k:None)
    monkeypatch.setattr(storage,'ensure_default_storage_dirs',lambda:None)
    dialog=settings_dialog.SettingsDialog(visible_sections=(visible,))
    qtbot.addWidget(dialog)
    dialog._save()
    assert dialog.result()==dialog.DialogCode.Accepted
    for key,(group,value) in sentinels.items():
        if group!=visible:assert settings.value(key)==value
