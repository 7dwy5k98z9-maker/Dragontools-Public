"""Hardlink crash cleanup requires prior receipts, not fresh self-certification."""
import os
from pathlib import Path
import pytest
from dragontools.core.move_journal_recovery import recover_interrupted_backups
from dragontools.core.move_journal import MoveJournal,MoveJournalWriteError
from dragontools.core.move_file_service import MoveFileService
from dragontools.core.transaction_identity import path_receipt


@pytest.mark.parametrize('proof',['missing','invalid','changed'])
def test_unproven_hardlink_alias_is_never_destructively_collapsed(tmp_path,proof):
    source=tmp_path/'source.mkv'; destination=tmp_path/'target.mkv'
    source.write_bytes(b'original'); expected=path_receipt(source)
    os.link(source,destination)
    row={'status':'running','phase':'video_pending','dest_path':str(destination),'backup_pairs':[]}
    if proof!='missing':
        row['commit_proof']={'source':expected,'destination':expected}
    if proof=='invalid': row['commit_proof']['source']={}
    if proof=='changed': source.write_bytes(b'changed-user-content')
    before=source.read_bytes()
    result=recover_interrupted_backups({'files':{str(source):row}})
    assert source.read_bytes()==destination.read_bytes()==before
    assert result['cleaned']==0 and result['completed']==0
    assert result['ambiguous']==1


def _move(source,target,journal):
    return MoveFileService(conflict_mode='skip',log=lambda *a:None,wait=lambda:None,
        abort_immediately=lambda:False,journal=journal).move(str(source),str(target))


def test_hard_crash_after_link_has_durable_expected_receipts(tmp_path,monkeypatch):
    import dragontools.core.move_transfer_executor as module
    class Crash(BaseException): pass
    source=tmp_path/'source.mkv'; source.write_bytes(b'original')
    target=tmp_path/'target'; target.mkdir(); destination=target/source.name
    journal=MoveJournal.start(files=[str(source)],root=tmp_path)
    journal.start_file(str(source),target_dir=str(target),dest_path=str(destination))
    link=module.os.link
    def crash_after_link(src,dst):
        link(src,dst)
        raise Crash('simulated process loss between link and source cleanup')
    monkeypatch.setattr(module.os,'link',crash_after_link)
    with pytest.raises(Crash): _move(source,target,journal)
    import json
    durable=json.loads(journal.path.read_text(encoding='utf-8'))
    assert durable['files'][str(source)].get('commit_proof'), 'intent predates the crash window'
    assert source.exists() and destination.exists()
    result=recover_interrupted_backups(durable)
    assert result['cleaned']==1 and not source.exists()
    assert destination.read_bytes()==b'original'
    repeated=recover_interrupted_backups(durable)
    assert repeated['cleaned']==0 and repeated['completed']==0


def test_intent_write_failure_blocks_link_and_preserves_source(tmp_path,monkeypatch):
    source=tmp_path/'source.mkv'; source.write_bytes(b'original')
    target=tmp_path/'target'; target.mkdir(); destination=target/source.name
    journal=MoveJournal.start(files=[str(source)],root=tmp_path)
    journal.start_file(str(source),target_dir=str(target),dest_path=str(destination))
    def fail(*a): raise MoveJournalWriteError('injected durable intent failure')
    monkeypatch.setattr(journal,'set_commit_proof',fail)
    with pytest.raises(MoveJournalWriteError): _move(source,target,journal)
    assert source.read_bytes()==b'original' and not destination.exists()
