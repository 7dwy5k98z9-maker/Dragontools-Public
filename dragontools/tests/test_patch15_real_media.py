"""Real H.264/AAC files and Qt JPEG companions through the actual MoveThread batch."""
import hashlib
import json
from pathlib import Path
import subprocess

import pytest
from PyQt6.QtGui import QImage

from dragontools.tests.test_patch14_real_media import tools, video
from dragontools.worker.move_thread import MoveThread

pytestmark = pytest.mark.media_integration


@pytest.mark.parametrize('container', ['mkv', 'mp4'])
@pytest.mark.parametrize('copy_fallback', [False, True])
def test_actual_move_batch_preserves_media_companions_and_unicode_year(tmp_path, tools, monkeypatch, container, copy_fallback):
    source = tmp_path / 'Quellen mit Leerzeichen'
    source.mkdir()
    path = source / f'Ranma ½ - S01E01.{container}'
    video(tools, path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    nfo = path.with_suffix('.nfo')
    nfo.write_text('<episodedetails><title>Ranma ½</title><year>2024</year></episodedetails>', encoding='utf-8')
    subtitle = path.with_suffix('.de.srt')
    subtitle.write_text('1\n00:00:00,000 --> 00:00:01,000\nHallo ½\n', encoding='utf-8')
    cache = path.with_suffix('.trickplay')
    images = cache / '320 - 10x10'
    images.mkdir(parents=True)
    image = QImage(32, 18, QImage.Format.Format_RGB32)
    image.fill(0x00808080)
    assert image.save(str(images / '0.jpg'), 'JPEG')
    companions = [nfo, subtitle, cache]
    original_bytes = {p.name: p.read_bytes() for p in [nfo, subtitle, images / '0.jpg']}
    base = tmp_path / 'Anime'
    target = base / 'Ranma ½ (2024)' / 'Staffel 01'
    worker = MoveThread([str(path)], '', str(base), '',
        planned_targets={str(path): {'target': target}},
        sidecar_outputs_by_video={str(path): [str(p) for p in companions]},
        move_journal_root=tmp_path, log_file_path=str(tmp_path / 'move.log'))
    worker._record_media_library_move = lambda *a: None
    terminal = []
    worker.batch_finished.connect(lambda *a: terminal.append(a))
    if copy_fallback:
        import dragontools.core.move_transfer_executor as transfer
        monkeypatch.setattr(transfer.os, 'link', lambda *a, **k: (_ for _ in ()).throw(OSError('copy fallback requested')))
    worker.run()
    assert len(terminal) == 1 and terminal[0][0] is True
    assert worker.ok_count == 1 and worker.error_count == 0
    destination = target / path.name
    assert destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() == digest
    assert not path.exists() and all(not p.exists() for p in companions)
    for p in (target / nfo.name, target / subtitle.name, target / cache.name / images.name / '0.jpg'):
        assert p.read_bytes() == original_bytes[p.name]
    assert not QImage(str(target / cache.name / images.name / '0.jpg')).isNull()
    probe = subprocess.run([tools.ffprobe, '-v', 'error', '-show_streams', '-of', 'json', str(destination)],
        capture_output=True, timeout=30)
    assert probe.returncode == 0, probe.stderr
    streams = json.loads(probe.stdout)['streams']
    assert [s['codec_name'] for s in streams] == ['h264', 'aac']
    assert streams[1]['tags']['language'] == 'deu'
    archives = list((tmp_path / 'MoveJournal' / 'Abgeschlossen').glob('*.json'))
    assert len(archives) == 1 and not list((tmp_path / 'MoveJournal').glob('move_*.json'))
    data = json.loads(archives[0].read_text(encoding='utf-8'))
    row = data['files'][str(path)]
    assert row['status'] == 'ok' and row['commit_proof']['destination']['content']
    assert len(row['companion_proofs']) == 3
    assert data['planned_targets'][str(path)]['target'] == str(target)
