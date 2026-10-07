from pathlib import Path
import pytest
import unicodedata
from dragontools.core.movie_identity import movie_identity_for_path
from dragontools.core.move_conflicts import find_target_conflicts
from dragontools.core.move_file_service import MoveFileService

@pytest.mark.parametrize('dash',['–','—','−','-'])
def test_actual_replacement_uses_movie_identity(tmp_path,dash):
    library=tmp_path/'library';library.mkdir()
    old=library/f'Star Wars Episode I {dash} Die dunkle Bedrohung (1999).mkv';old.write_bytes(b'old-good')
    src=tmp_path/'Star Wars Episode I - Die dunkle Bedrohung (1999).mkv';src.write_bytes(b'new-verified')
    dst=library/src.name
    assert find_target_conflicts(dst,src)==[old]
    service=MoveFileService(conflict_mode='overwrite',log=lambda *a:None,wait=lambda:None,abort_immediately=lambda:False)
    prepared=service.prepare_move(src,library)
    ok,result=service.move(src,library,prepared=prepared)
    assert ok,result
    assert list(library.glob('*.mkv'))==[dst]
    assert dst.read_bytes()==b'new-verified'

def test_ambiguous_canonical_movies_are_preserved(tmp_path):
    library=tmp_path/'library';library.mkdir()
    for dash in ('–','—'):(library/f'Film {dash} Titel (1999).mkv').write_bytes(b'good')
    src=tmp_path/'Film - Titel (1999).mkv';src.write_bytes(b'new')
    service=MoveFileService(conflict_mode='overwrite',log=lambda *a:None,wait=lambda:None,abort_immediately=lambda:False)
    prepared=service.prepare_move(src,library)
    assert prepared['ready'] is False
    assert all(p.read_bytes()==b'good' for p in library.glob('*.mkv'))

@pytest.mark.parametrize('left,right,expected',[
    ('Änne – O’Neil (1999)','Änne - O\'Neil (1999)',True),
    ('Film\u00a0– Titel (1999)','Film - Titel (1999)',True),
    ('Film (1999)','Film (2020)',False),
    ('Film (1999) Extended','Film (1999) Theatrical',False),
    ('Film','Film',False),
    ('Film Eins (1999)','Film Zwei (1999)',False)])
def test_movie_identity_unicode_remakes_editions_and_unknown_year(left,right,expected):
    assert movie_identity_for_path(Path(left+'.mkv')).matches(movie_identity_for_path(Path(right+'.mkv'))) is expected

def test_metadata_ids_prevent_wrong_film_replacement(tmp_path):
    library=tmp_path/'library';library.mkdir()
    old=library/'Film – Titel (1999).mkv';old.write_bytes(b'good')
    old.with_suffix('.nfo').write_text('<movie><uniqueid type="tmdb">1</uniqueid></movie>',encoding='utf-8')
    src=tmp_path/'Film - Titel (1999).mkv';src.write_bytes(b'new')
    src.with_suffix('.nfo').write_text('<movie><uniqueid type="tmdb">2</uniqueid></movie>',encoding='utf-8')
    assert find_target_conflicts(library/src.name,src)==[]

def test_movie_replacement_removes_only_owned_old_companions(tmp_path):
    library=tmp_path/'library';library.mkdir()
    old=library/'Film – Titel (1999).mkv';old.write_bytes(b'good')
    subtitle=old.with_suffix('.de.srt');subtitle.write_text('old subtitle',encoding='utf-8')
    unrelated=library/'Other Film (2000).srt';unrelated.write_text('keep',encoding='utf-8')
    src=tmp_path/'Film - Titel (1999).mkv';src.write_bytes(b'new')
    service=MoveFileService(conflict_mode='overwrite',log=lambda *a:None,wait=lambda:None,abort_immediately=lambda:False)
    prepared=service.prepare_move(src,library)
    ok,result=service.move(src,library,prepared=prepared)
    assert ok,result
    assert not old.exists() and not subtitle.exists() and unrelated.read_text()=='keep'

def test_movie_commit_failure_restores_good_file_and_companions(tmp_path,monkeypatch):
    import dragontools.core.move_transfer_executor as transaction
    library=tmp_path/'library';library.mkdir()
    old=library/'Film – Titel (1999).mkv';old.write_bytes(b'good')
    companion=old.with_suffix('.srt');companion.write_text('keep',encoding='utf-8')
    src=tmp_path/'Film - Titel (1999).mkv';src.write_bytes(b'new')
    def fail_commit(*a,**kw):
        raise PermissionError('simulated locked destination')
    service=MoveFileService(conflict_mode='overwrite',log=lambda *a:None,wait=lambda:None,abort_immediately=lambda:False)
    prepared=service.prepare_move(src,library)
    monkeypatch.setattr(transaction.os,'link',fail_commit)
    monkeypatch.setattr(transaction,'publish_staged_no_replace',fail_commit)
    ok,result=service.move(src,library,prepared=prepared)
    assert not ok,result
    assert old.read_bytes()==b'good' and companion.read_text()=='keep' and src.read_bytes()==b'new'
