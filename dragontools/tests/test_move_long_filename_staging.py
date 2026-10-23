from __future__ import annotations

import errno
from pathlib import Path
from types import SimpleNamespace

import pytest

from dragontools.core.move_transaction import unique_staging_path
from dragontools.core.move_file_service import MoveFileService


LONG_EPISODE_NAME = (
    'The Laid-Off Cheat-Granting Mage Enjoys a Second Lease on Life - S01E02 - '
    'Als meine verstärkten Klamotten sich mit einem Angriff in Luft auflösen, '
    'haut mich das traumatisierte Mädchen in seinem Freizeit-Outfit aus dem Leben.mkv'
)


@pytest.mark.parametrize('name', [LONG_EPISODE_NAME, 'x' * 251 + '.mkv', 'ä' * 120 + '.mkv'])
def test_staging_name_stays_short_even_for_maximum_length_or_utf8_names(tmp_path, name):
    target = tmp_path / name
    stage = unique_staging_path(target)
    assert stage.parent == target.parent
    assert len(stage.name.encode('utf-8')) < 255
    assert len(stage.name.encode('utf-16-le')) // 2 < 255
    assert stage.name.startswith('.__dragontools_partial__')
    assert target.name == name


def test_staging_collision_preserves_foreign_file_and_chooses_another_name(tmp_path, monkeypatch):
    from dragontools.core import move_transaction
    foreign = tmp_path / '.__dragontools_partial__0123456789'
    foreign.write_bytes(b'foreign')
    tokens = iter(['0123456789abcdef', 'fedcba9876543210'])
    monkeypatch.setattr(move_transaction.uuid, 'uuid4', lambda: SimpleNamespace(hex=next(tokens)))
    stage = unique_staging_path(tmp_path / LONG_EPISODE_NAME, attempts=2)
    assert stage.name == '.__dragontools_partial__fedcba9876'
    assert foreign.read_bytes() == b'foreign'


def test_cross_volume_move_of_reported_episode_keeps_full_filename(tmp_path, monkeypatch):
    from dragontools.core import move_transfer_executor

    source_dir = tmp_path / 'source'
    destination_dir = tmp_path / 'target'
    source_dir.mkdir()
    destination_dir.mkdir()
    source = source_dir / LONG_EPISODE_NAME
    source.write_bytes(b'complete verified episode content')

    def no_hardlink(*_args, **_kwargs):
        raise OSError(errno.EXDEV, 'cross-volume move')

    monkeypatch.setattr(move_transfer_executor.os, 'link', no_hardlink)
    service = MoveFileService(
        conflict_mode='skip', log=lambda *_args: None,
        wait=lambda: None, abort_immediately=lambda: False, journal=None,
    )
    ok, result = service.move(source, destination_dir)
    target = destination_dir / LONG_EPISODE_NAME
    assert ok is True and result['ok'] is True
    assert target.read_bytes() == b'complete verified episode content'
    assert not source.exists()
    assert not list(destination_dir.glob('*.__dragontools_partial__*'))


def test_short_staging_path_keeps_foreign_destination_on_publish_collision(tmp_path):
    from dragontools.core.move_transaction import publish_staged_no_replace
    destination = tmp_path / LONG_EPISODE_NAME
    stage = unique_staging_path(destination)
    stage.write_bytes(b'new payload')
    destination.write_bytes(b'foreign destination')
    with pytest.raises(FileExistsError):
        publish_staged_no_replace(stage, destination)
    assert stage.read_bytes() == b'new payload'
    assert destination.read_bytes() == b'foreign destination'
