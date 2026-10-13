"""Copy receipts remove repeated reads without authorizing stale cleanup."""
from collections import Counter
from pathlib import Path
import os

import pytest

from dragontools.core.move_copy_verification import verify_staged_file_copy
from dragontools.core.move_file_service import MoveFileService
from dragontools.core.transaction_identity import path_receipt


def _copy_service(monkeypatch, journal=None):
    from dragontools.core import move_transfer_executor as transfer

    def cross_volume(*args, **kwargs):
        raise OSError('cross-volume')

    monkeypatch.setattr(transfer.os, 'link', cross_volume)
    return MoveFileService(conflict_mode='skip', log=lambda *args: None,
        wait=lambda: None, abort_immediately=lambda: False, journal=journal)


def _paths(tmp_path):
    source = tmp_path / 'source.mkv'
    source.write_bytes(b'original' * 300_000)
    target = tmp_path / 'target'
    target.mkdir()
    return source, target, target / source.name


def test_full_copy_comparison_produces_existing_journal_receipt_format(tmp_path):
    source, target, destination = _paths(tmp_path)
    destination.write_bytes(source.read_bytes())
    proof = verify_staged_file_copy(source, destination)
    assert proof.source_receipt == path_receipt(source)
    assert proof.staged_receipt == path_receipt(destination)


def test_cross_volume_move_reduces_full_reads_but_rechecks_before_deletion(tmp_path, monkeypatch):
    from dragontools.core import transaction_identity as identity

    source, target, destination = _paths(tmp_path)
    service = _copy_service(monkeypatch)
    reads = Counter()
    original = identity._content_digest

    def tracked(path):
        reads[Path(path)] += 1
        return original(path)

    monkeypatch.setattr(identity, '_content_digest', tracked)
    ok, result = service.move(source, target)
    assert ok and result['ok']
    assert destination.read_bytes() == b'original' * 300_000
    assert not source.exists()
    # Preparation, validation at handoff, and a fresh check before deletion.
    # The full byte comparison also produces the hash of the copied contents.
    assert reads[source] == 3
    assert reads[destination] == 1


@pytest.mark.parametrize('changed_path', ['source', 'destination'])
def test_changed_contents_after_journal_write_never_authorize_source_deletion(
        tmp_path, monkeypatch, changed_path):
    source, target, destination = _paths(tmp_path)
    original_contents = source.read_bytes()

    class MutatingJournal:
        data = {'files': {str(source): {}}}

        def set_destination(self, *args, **kwargs):
            pass

        def set_commit_proof(self, *args, **kwargs):
            if not destination.exists():
                return
            changed = source if changed_path == 'source' else destination
            previous = changed.stat()
            changed.write_bytes(b'mutated!' * 300_000)
            os.utime(changed, ns=(previous.st_atime_ns, previous.st_mtime_ns))

    service = _copy_service(monkeypatch, journal=MutatingJournal())
    ok, result = service.move(source, target)
    assert not ok and not result['ok']
    assert source.exists()
    if changed_path == 'destination':
        assert source.read_bytes() == original_contents
        assert destination.read_bytes() == b'mutated!' * 300_000
    else:
        assert source.read_bytes() == b'mutated!' * 300_000
        assert not destination.exists()


def test_copy_changed_since_preparation_is_rejected_even_when_copy_matches(tmp_path, monkeypatch):
    from dragontools.core import move_transfer_executor as transfer

    source, target, destination = _paths(tmp_path)
    service = _copy_service(monkeypatch)
    original_verify = transfer.verify_staged_file_copy

    def change_both_before_verification(src, staged):
        Path(src).write_bytes(b'changed!' * 300_000)
        Path(staged).write_bytes(b'changed!' * 300_000)
        return original_verify(src, staged)

    monkeypatch.setattr(transfer, 'verify_staged_file_copy', change_both_before_verification)
    ok, result = service.move(source, target)
    assert not ok and not result['ok']
    assert source.read_bytes() == b'changed!' * 300_000
    assert not destination.exists()
