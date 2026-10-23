from __future__ import annotations

from contextlib import closing
from threading import Event, get_ident
from types import MethodType, SimpleNamespace
import sqlite3

import pytest

pytest.importorskip('PyQt6')
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QCheckBox, QDialog, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QTabWidget, QWidget

from dragontools.core.media_library_jellyfin import import_jellyfin_database
from dragontools.core.media_library_types import PathMapping
from dragontools.gui.media_library_dialog_view import MediaLibraryDialogView
from dragontools.gui.media_library_maintenance_controller import MediaLibraryMaintenanceController
from dragontools.tests.test_media_library import _create_minimal_jellyfin_db


def test_core_progress_includes_skipped_rows_and_finalization(tmp_path):
    source=tmp_path/'jellyfin.db'
    target=tmp_path/'library.db'
    _create_minimal_jellyfin_db(source)
    with closing(sqlite3.connect(source)) as c, c:
        c.executemany('INSERT INTO TypedBaseItems(Guid,Type,Name,Path) VALUES(?,?,?,?)',[
            (f'folder-{i}','MediaBrowser.Controller.Entities.Folder',f'Folder {i}',f'/Unmapped/{i}') for i in range(150)
        ])
    source_bytes=source.read_bytes()
    progress=[]
    result=import_jellyfin_database(source,target,[
        PathMapping('Anime','/Anime',str(tmp_path/'Anime')),
        PathMapping('Filme','/Filme',str(tmp_path/'Filme')),
    ],progress=lambda *args:progress.append(args))
    assert result.imported_items==2 and result.skipped_items==150
    determinate=[(current,total) for current,total,_message in progress if total>0]
    assert determinate==[(0,152),(99,152),(152,152)]
    assert any('kopiert' in message for _,_,message in progress)
    assert progress[-1]==(0,0,'Neue Mediathek wird übernommen …')
    assert source.read_bytes()==source_bytes


@pytest.fixture
def ui(qtbot,monkeypatch):
    parent=QDialog()
    qtbot.addWidget(parent)
    tabs=QTabWidget(parent)
    for label in ('Status','Mapping','Suchen','Bearbeiten'):
        tabs.addTab(QWidget(),label)
    enabled=QCheckBox(parent)
    enabled.setEnabled(False)
    button=QPushButton(parent)
    view=SimpleNamespace(
        jellyfin_path_edit=QLineEdit('source.db',parent),analyze_import_cb=QCheckBox(parent),
        import_progress=QProgressBar(parent),import_status_label=QLabel(parent),stats_label=QLabel(parent),
        tabs=tabs,scan_sensitive_widgets=[button],fix_sensitive_widgets=[],import_sensitive_widgets=[enabled],
    )
    view.set_import_running=MethodType(MediaLibraryDialogView.set_import_running,view)
    messages=[]
    monkeypatch.setattr(QMessageBox,'question',lambda *_args:QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox,'information',lambda *args:messages.append(('ok',get_ident(),args[-1])))
    monkeypatch.setattr(QMessageBox,'critical',lambda *args:messages.append(('error',get_ident(),args[-1])))
    return parent,view,button,enabled,messages


def controller_for(ui,service,other_task=lambda:False):
    parent,view,*_=ui
    return MediaLibraryMaintenanceController(
        parent=parent,view=view,service=service,
        presenter=SimpleNamespace(format_import_result=lambda result:f'Imported {result}',format_stats=lambda stats:'refreshed'),
        settings=object(),get_db_path=lambda:'target.db',get_mappings=lambda:[],save_state=lambda:None,
        other_task_running=other_task,
    )


def test_import_keeps_gui_timer_running_and_queues_progress_to_gui(ui,qtbot):
    from dragontools.gui.application_worker_sources import application_worker_sources
    from dragontools.gui.application_shutdown import collect_shutdown_workers
    from dragontools.gui.media_library_import_worker import active_media_library_import_workers

    started,release=Event(),Event()
    calls=[]
    gui_thread=get_ident()
    def importing(*args,progress,**kwargs):
        calls.append(get_ident())
        started.set()
        progress(0,0,'Quelle wird kopiert')
        progress(1,4,'Einträge prüfen: 1/4')
        assert release.wait(5)
        return 'result'
    service=SimpleNamespace(import_jellyfin=importing,tool_paths=lambda _settings:None,stats=lambda _path:None)
    controller=controller_for(ui,service)
    parent,view,button,disabled,messages=ui
    timer=QTimer(parent)
    ticks=[]
    timer.timeout.connect(lambda:ticks.append(True))
    timer.start(10)
    try:
        controller.import_jellyfin(lambda:None)
        qtbot.waitUntil(started.is_set)
        qtbot.waitUntil(lambda:len(ticks)>=3 and view.import_progress.value()==25)
        assert controller.is_running and calls==[calls[0]] and calls[0]!=gui_thread
        assert not button.isEnabled() and not view.tabs.isTabEnabled(2)
        assert '1/4' in view.import_status_label.text()
        worker=controller._import_worker
        assert worker in active_media_library_import_workers()
        assert worker in collect_shutdown_workers(application_worker_sources(SimpleNamespace(_tab_widgets={})))
        controller.import_jellyfin(lambda:None)
        assert len(calls)==1
    finally:
        release.set()
        qtbot.waitUntil(lambda:not controller.is_running,timeout=5000)
        timer.stop()
    assert button.isEnabled() and not disabled.isEnabled()
    assert view.tabs.isTabEnabled(2)
    assert view.import_progress.value()==100
    assert view.import_status_label.text()=='Jellyfin-Import abgeschlossen.'
    assert all(thread==gui_thread for _kind,thread,_message in messages)


def test_failed_background_import_restores_controls_and_reports_error(ui,qtbot):
    def failing(*_args,**_kwargs):
        raise OSError('Quelle nicht lesbar')
    controller=controller_for(ui,SimpleNamespace(import_jellyfin=failing,tool_paths=lambda _s:None))
    controller.import_jellyfin(lambda:None)
    qtbot.waitUntil(lambda:not controller.is_running)
    _parent,view,button,disabled,messages=ui
    assert button.isEnabled() and not disabled.isEnabled()
    assert view.import_progress.minimum()==0 and view.import_progress.maximum()==100
    assert view.import_progress.value()==0
    assert messages==[('error',get_ident(),'Quelle nicht lesbar')]


def test_import_does_not_start_during_other_library_task(ui):
    calls=[]
    controller=controller_for(ui,SimpleNamespace(import_jellyfin=lambda *a,**k:calls.append(True)),other_task=lambda:True)
    controller.import_jellyfin(lambda:None)
    assert not controller.is_running and calls==[]


@pytest.mark.parametrize('action',['close','reject','accept'])
def test_native_dialog_cannot_close_during_background_import(qtbot,monkeypatch,action):
    from dragontools.gui.media_library_dialog import MediaLibraryDialog
    dialog=MediaLibraryDialog.__new__(MediaLibraryDialog)
    QDialog.__init__(dialog)
    qtbot.addWidget(dialog)
    dialog._scan=dialog._nfo=dialog._fix=SimpleNamespace(is_running=False)
    dialog._maintenance=SimpleNamespace(is_running=True)
    dialog._search=SimpleNamespace(shutdown=lambda:True)
    dialog._save_without_popup=lambda:None
    monkeypatch.setattr(QMessageBox,'information',lambda *_args:None)
    monkeypatch.setattr('dragontools.gui.media_library_dialog.save_window_geometry',lambda *_args:None)
    dialog.settings=None
    dialog.show()
    getattr(dialog,action)()
    assert dialog.isVisible()
    dialog._maintenance.is_running=False
    dialog.close()
