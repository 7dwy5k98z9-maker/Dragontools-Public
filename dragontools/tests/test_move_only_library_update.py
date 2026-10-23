from __future__ import annotations

from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
import builtins
import sqlite3

import pytest

from dragontools.core.media_library_db import _connect, initialize_database
from dragontools.core.media_library_item_sql import _insert_item
from dragontools.core.media_library_repository_moves import record_moved_file
from dragontools.core.path_syntax import path_compare_key
from dragontools.core.settings_media_library import SET_KEY_MEDIA_LIBRARY_DB_PATH, SET_KEY_MEDIA_LIBRARY_ENABLED
from dragontools.tests.test_review20_media_library_safety import _item
from dragontools.tests.test_media_library import _fake_media_info


def add_catalog_entry(db, source):
    item=_item(str(source),'Bestätigter Filmtitel')
    item.update(year=2024,original_title='Confirmed Original Title',source='jellyfin',source_id='original-jellyfin-id')
    with closing(_connect(db)) as c, c:
        media_id=_insert_item(c,item,[])
        c.execute("INSERT INTO media_provider_ids VALUES(?,'tmdb','12345','jellyfin')",(media_id,))
        c.execute("INSERT INTO metadata_values(kind,value,normalized_value) VALUES('genre','Fantasy','fantasy')")
        value_id=c.execute("SELECT id FROM metadata_values WHERE kind='genre'").fetchone()[0]
        c.execute('INSERT INTO media_item_values VALUES(?,?,0)',(media_id,value_id))
        c.execute("INSERT INTO people(source_id,name) VALUES('actor-id','Actor')")
        person_id=c.execute('SELECT id FROM people').fetchone()[0]
        c.execute("INSERT INTO media_people VALUES(?,?,'Actor','Role',0)",(media_id,person_id))
        c.execute("INSERT INTO collections(source,source_id,name) VALUES('jellyfin','collection-id','Collection')")
        collection_id=c.execute('SELECT id FROM collections').fetchone()[0]
        c.execute('INSERT INTO collection_members VALUES(?,?,0)',(collection_id,media_id))
    return media_id


def worker_for(tmp_path,db,source,monkeypatch,*,enabled=True):
    pytest.importorskip('PyQt6')
    from dragontools.worker.move_thread import MoveThread
    from dragontools.core.logger import DragonLogger
    values={SET_KEY_MEDIA_LIBRARY_DB_PATH:str(db),SET_KEY_MEDIA_LIBRARY_ENABLED:enabled}
    settings=SimpleNamespace(value=lambda key,default=None,**_kwargs:values.get(key,default))
    monkeypatch.setattr('dragontools.worker.move_result_commit.worker_settings_snapshot',lambda:settings)
    monkeypatch.setattr('dragontools.core.media_analyzer.analyze_media',_fake_media_info)
    monkeypatch.setattr('dragontools.worker.move_thread.create_worker_logger',
                        lambda **kwargs:DragonLogger(tmp_path/'logs',gui_callback=kwargs.get('gui_callback')))
    root=tmp_path/'Filme'
    target=root/'B'/'Bestätigter Filmtitel (2024)'
    worker=MoveThread([str(source)],tv_path='',anime_path='',filme_path=str(root),
        planned_targets={str(source):str(target)},log_file_path=str(tmp_path/'move.log'),
        move_journal_root=tmp_path/'journal')
    return worker,target/source.name


def test_move_only_updates_path_and_preserves_imported_metadata(tmp_path,monkeypatch):
    db=initialize_database(tmp_path/'library.db')
    source=tmp_path/'file.mkv'
    source.write_bytes(b'media content')
    source_id=add_catalog_entry(db,source)
    worker,target=worker_for(tmp_path,db,source,monkeypatch)
    logs=[]
    worker.log_line.connect(logs.append)
    worker.run()
    assert worker.ok_count==1 and worker.error_count==0
    assert target.read_bytes()==b'media content' and not source.exists()
    with closing(_connect(db)) as c:
        old=c.execute('SELECT active,exists_flag FROM media_items WHERE id=?',(source_id,)).fetchone()
        new=c.execute('SELECT * FROM media_items WHERE path_key=?',(path_compare_key(str(target)),)).fetchone()
        assert tuple(old)==(0,0)
        assert new['active']==1 and new['exists_flag']==1
        assert new['title']=='Bestätigter Filmtitel' and new['year']==2024
        assert new['original_title']=='Confirmed Original Title'
        assert new['source_id']=='original-jellyfin-id'
        assert new['parent_path']==str(target.parent) and new['filename']==source.name
        for table in ('media_provider_ids','media_item_values','media_people','collection_members'):
            assert c.execute(f'SELECT count(*) FROM {table} WHERE media_id=?',(new['id'],)).fetchone()[0]==1
        assert c.execute('SELECT count(*) FROM media_items WHERE active=1 AND exists_flag=1').fetchone()[0]==1
    assert any('Mediathek-DB aktualisiert' in message for message in logs)


def test_move_only_adds_a_previously_unknown_video_to_enabled_library(tmp_path,monkeypatch):
    db=initialize_database(tmp_path/'library.db')
    source=tmp_path/'New movie.mkv'
    source.write_bytes(b'media content')
    worker,target=worker_for(tmp_path,db,source,monkeypatch)
    worker.run()
    assert worker.ok_count==1
    with closing(_connect(db)) as c:
        assert c.execute('SELECT path FROM media_items WHERE active=1').fetchone()[0]==str(target)


def test_repeated_completion_preserves_catalog_and_does_not_add_active_duplicate(tmp_path,monkeypatch):
    db=initialize_database(tmp_path/'library.db')
    source=tmp_path/'file.mkv'
    source.write_bytes(b'media content')
    add_catalog_entry(db,source)
    worker,target=worker_for(tmp_path,db,source,monkeypatch)
    worker.run()
    record_moved_file(db,source,target)
    with closing(_connect(db)) as c:
        active=c.execute('SELECT id,title,year FROM media_items WHERE active=1 AND exists_flag=1').fetchall()
        assert len(active)==1 and active[0]['title']=='Bestätigter Filmtitel'
        assert active[0]['year']==2024
        assert c.execute('SELECT count(*) FROM media_provider_ids WHERE media_id=?',(active[0]['id'],)).fetchone()[0]==1


def test_failed_move_only_does_not_change_catalog_paths(tmp_path,monkeypatch):
    db=initialize_database(tmp_path/'library.db')
    source=tmp_path/'file.mkv'
    source.write_bytes(b'media content')
    source_id=add_catalog_entry(db,source)
    worker,target=worker_for(tmp_path,db,source,monkeypatch)
    monkeypatch.setattr('dragontools.core.move_transfer_executor.os.link',lambda *_a,**_k:(_ for _ in ()).throw(OSError('cross volume')))
    original_open=builtins.open
    def fail_staging(path,mode='r',*args,**kwargs):
        if mode=='xb' and '.__dragontools_partial__' in Path(path).name:
            raise PermissionError('copy failed')
        return original_open(path,mode,*args,**kwargs)
    monkeypatch.setattr(builtins,'open',fail_staging)
    worker.run()
    assert worker.error_count==1 and worker.ok_count==0
    assert source.exists() and not target.exists()
    with closing(_connect(db)) as c:
        assert tuple(c.execute('SELECT path,active,exists_flag FROM media_items WHERE id=?',(source_id,)).fetchone())==(str(source),1,1)
        assert c.execute('SELECT count(*) FROM media_items').fetchone()[0]==1


def test_move_only_respects_disabled_library_setting(tmp_path,monkeypatch):
    db=initialize_database(tmp_path/'library.db')
    source=tmp_path/'file.mkv'
    source.write_bytes(b'media content')
    worker,_target=worker_for(tmp_path,db,source,monkeypatch,enabled=False)
    worker.run()
    assert worker.ok_count==1
    with closing(_connect(db)) as c:
        assert c.execute('SELECT count(*) FROM media_items').fetchone()[0]==0


def test_metadata_transfer_and_path_update_roll_back_together(tmp_path,monkeypatch):
    from dragontools.core import media_library_repository_moves as module
    db=initialize_database(tmp_path/'library.db')
    source=tmp_path/'source.mkv'
    target=tmp_path/'destination.mkv'
    target.write_bytes(b'committed media')
    source_id=add_catalog_entry(db,source)
    monkeypatch.setattr('dragontools.core.media_analyzer.analyze_media',_fake_media_info)
    monkeypatch.setattr(module,'_transfer_catalog_links',lambda *_args:(_ for _ in ()).throw(sqlite3.OperationalError('metadata write failed')))
    with pytest.raises(sqlite3.OperationalError,match='metadata write failed'):
        record_moved_file(db,source,target)
    with closing(_connect(db)) as c:
        assert tuple(c.execute('SELECT active,exists_flag FROM media_items WHERE id=?',(source_id,)).fetchone())==(1,1)
        assert c.execute('SELECT count(*) FROM media_items').fetchone()[0]==1
