"""Verify actual CPU-rendered JPEGs and NFO stream metadata at publication."""
from pathlib import Path
import subprocess
from types import SimpleNamespace as NS
import xml.etree.ElementTree as ET

import pytest
from PyQt6.QtGui import QImageReader

from dragontools.tests.ci_requirements import external_media_environment
from dragontools.core.online_metadata import MovieMetadataSuggestion
from dragontools.core.settings_postprocess import (
    SET_KEY_NFO_ENABLED, SET_KEY_NFO_TIMING, SET_KEY_NFO_FILEINFO_ENABLED,
    SET_KEY_TRICKPLAY_ENABLED, SET_KEY_TRICKPLAY_SOURCE_MODE,
    SET_KEY_TRICKPLAY_HWACCEL, SET_KEY_TRICKPLAY_CONFLICT_MODE,
    SET_KEY_TRICKPLAY_INTERVAL_S,
)
from dragontools.tests.test_patch14_second_review import DummySettings
from dragontools.worker.postprocess_runner import PostProcessService
from dragontools.worker.trickplay_service import TrickplayGenerator, TrickplaySettings

pytestmark = pytest.mark.media_integration


@pytest.fixture
def tools():
    env = external_media_environment()
    if not env.ffmpeg or not env.ffprobe:
        pytest.skip('FFmpeg und ffprobe erforderlich')
    return NS(ffmpeg=env.ffmpeg, ffprobe=env.ffprobe)


def video(tools, path):
    result = subprocess.run([tools.ffmpeg, '-y', '-v', 'error', '-f', 'lavfi', '-i',
        'testsrc2=size=160x90:rate=25:duration=2', '-f', 'lavfi', '-i',
        'sine=frequency=440:duration=2', '-c:v', 'libx264', '-preset', 'ultrafast',
        '-c:a', 'aac', '-metadata:s:a:0', 'language=deu', str(path)], capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('container', ['mkv', 'mp4'])
def test_real_source_cache_and_during_nfo_publish_only_after_video(tmp_path, tools, monkeypatch, container):
    source = tmp_path/f'Quelle ü.{container}'
    output = tmp_path/f'Installiert Ω.{container}'
    video(tools, source)
    settings = DummySettings({SET_KEY_NFO_ENABLED:True, SET_KEY_NFO_TIMING:'during',
        SET_KEY_NFO_FILEINFO_ENABLED:True, SET_KEY_TRICKPLAY_ENABLED:True,
        SET_KEY_TRICKPLAY_SOURCE_MODE:'source', SET_KEY_TRICKPLAY_HWACCEL:'none',
        SET_KEY_TRICKPLAY_INTERVAL_S:1,
        SET_KEY_TRICKPLAY_CONFLICT_MODE:'overwrite'})
    suggestion = MovieMetadataSuggestion(query_title='Test', query_year=2026, tmdb_id=1,
        title='Test', original_title='Test', release_year=2026)
    service = PostProcessService(settings=settings, tools=tools, log=None)
    monkeypatch.setattr(service, '_resolve_nfo_suggestion', lambda *a: ('movie', suggestion, ''))
    prepared_nfo = service.prepare_nfo_during_conversion(input_path=str(source),
        output_path=str(output), final_output_path=str(output))
    prepared_cache = service.prepare_source_trickplay(input_path=str(source), output_path=str(output))
    assert prepared_nfo.status == 'prepared'
    assert prepared_cache.prepared_trickplay is not None
    assert not output.with_suffix('.nfo').exists() and not output.with_suffix('.trickplay').exists()
    output.write_bytes(source.read_bytes())
    service.refresh_prepared_nfo(prepared_nfo, video_path=str(output))
    nfo_result = service.commit_prepared_nfo(prepared_nfo, final_output_path=str(output))
    cache_result = service.run_result(input_path=str(source), output_path=str(output),
        prepared_source_trickplay=prepared_cache)
    assert nfo_result.created_paths == [str(output.with_suffix('.nfo'))]
    root = ET.parse(output.with_suffix('.nfo')).getroot()
    assert root.findtext('fileinfo/streamdetails/video/codec') == 'h264'
    assert root.findtext('fileinfo/streamdetails/video/width') == '160'
    assert root.findtext('fileinfo/streamdetails/audio/codec') == 'aac'
    assert root.findtext('fileinfo/streamdetails/audio/language') == 'deu'
    assert cache_result.created_paths == [str(output.with_suffix('.trickplay'))]
    image = next(output.with_suffix('.trickplay').glob('*/*.jpg'))
    decoded = QImageReader(str(image), b'jpeg').read()
    assert not decoded.isNull() and decoded.width() == 3200 and decoded.height() == 1800
    assert not Path(prepared_nfo.staging_path).exists()
    assert not Path(prepared_cache.prepared_trickplay.staging_root).exists()


def test_real_cache_abort_after_render_keeps_previous_cache(tmp_path, tools, monkeypatch):
    source = tmp_path/'Video.mkv'; video(tools, source)
    old = source.with_suffix('.trickplay')/'320 - 10x10'; old.mkdir(parents=True)
    (old/'0.jpg').write_bytes(b'previous cache')
    worker = NS(abort_requested=False)
    generator = TrickplayGenerator(ffmpeg_path=tools.ffmpeg, log=None, worker=worker)
    original = generator._render_sprites
    def stop_after_render(*args):
        result = original(*args)
        assert result
        worker.abort_requested = True
        return result
    monkeypatch.setattr(generator, '_render_sprites', stop_after_render)
    assert generator.generate(source, TrickplaySettings(enabled=True, hwaccel='none', conflict_mode='overwrite', interval_s=1)) is None
    assert (old/'0.jpg').read_bytes() == b'previous cache'
    assert not list(tmp_path.glob('Video.trickplay.__partial__*'))


def test_real_prepared_cache_is_discarded_when_video_install_fails(tmp_path, tools):
    source = tmp_path/'source.mkv'; video(tools, source)
    output = tmp_path/'missing.mkv'
    settings = DummySettings({SET_KEY_TRICKPLAY_ENABLED:True, SET_KEY_TRICKPLAY_SOURCE_MODE:'source',
        SET_KEY_TRICKPLAY_HWACCEL:'none', SET_KEY_TRICKPLAY_INTERVAL_S:1})
    service = PostProcessService(settings=settings, tools=tools, log=None)
    prepared = service.prepare_source_trickplay(input_path=str(source), output_path=str(output))
    assert prepared.prepared_trickplay is not None
    result = service.run_result(input_path=str(source), output_path=str(output), prepared_source_trickplay=prepared)
    assert not result.created_paths and not output.with_suffix('.trickplay').exists()
    assert not Path(prepared.prepared_trickplay.staging_root).exists()
