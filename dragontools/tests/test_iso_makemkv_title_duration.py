"""MakeMKV chapter counts must never become verification durations."""
from pathlib import Path
from types import SimpleNamespace
import shutil
import subprocess

import pytest

from dragontools.worker.iso_makemkv_service import ISOMakeMKVService
from dragontools.worker.iso_selection import choose_main_title
from dragontools.worker.iso_title_parser import parse_makemkv_titles


def test_actual_movie_attributes_use_duration_instead_of_chapter_count():
    result = parse_makemkv_titles([
        'TINFO:0,2,0,"The Book of Eli"',
        'TINFO:0,8,0,"27"',
        'TINFO:0,9,0,"1:57:41"',
        'TINFO:0,10,0,"27.4 GB"',
        'TINFO:0,11,0,"29450108928"',
        'TINFO:0,16,0,"00002.mpls"',
    ])
    assert result == [{'id': 0, 'name': 'The Book of Eli', 'duration': 7061, 'size': 29450108928}]


@pytest.mark.parametrize('chapter_line', ['TINFO:0,8,0,"27"', 'TINFO:0,8,0,"00:01:00"'])
@pytest.mark.parametrize('chapter_first', [False, True])
def test_chapter_count_is_ignored_regardless_of_order_or_format(chapter_line, chapter_first):
    duration = 'TINFO:0,9,0,"1:57:41"'
    lines = [chapter_line, duration] if chapter_first else [duration, chapter_line]
    assert parse_makemkv_titles(lines)[0]['duration'] == 7061


def test_chapter_count_alone_cannot_supply_duration():
    assert parse_makemkv_titles(['TINFO:0,8,0,"27"']) == []
    parsed = parse_makemkv_titles(['TINFO:0,2,0,"Film"', 'TINFO:0,8,0,"27"'])
    assert parsed[0]['duration'] == 0


def test_main_title_choice_uses_film_duration_not_number_of_chapters():
    parsed = parse_makemkv_titles([
        'TINFO:0,8,0,"27"', 'TINFO:0,9,0,"1:57:41"',
        'TINFO:1,8,0,"80"', 'TINFO:1,9,0,"0:10:00"',
    ])
    assert choose_main_title(parsed) == 0


@pytest.mark.parametrize('value', ['"bad duration"', '"NaN"', 'null', '123', '"-1"'])
def test_invalid_duration_does_not_fall_back_to_chapter_count(value):
    parsed = parse_makemkv_titles(['TINFO:0,2,0,"Film"', 'TINFO:0,8,0,"27"', f'TINFO:0,9,0,{value}'])
    assert parsed[0]['duration'] == 0


@pytest.mark.media_integration
@pytest.mark.parametrize('reported_duration,expected_success', [('0:00:03', True), ('0:00:30', False)])
def test_real_mkv_verification_accepts_complete_output_and_rejects_truncated_output(tmp_path, reported_duration, expected_success):
    from dragontools.tests.ci_requirements import external_media_environment
    tools = external_media_environment()
    if not tools.ffmpeg or not tools.ffprobe:
        pytest.skip('FFmpeg/ffprobe unavailable')
    seed = tmp_path / 'seed.mkv'
    subprocess.run([
        tools.ffmpeg, '-v', 'error', '-nostdin', '-n', '-f', 'lavfi', '-i',
        'testsrc2=size=160x90:rate=25:duration=3', '-c:v', 'libx264', '-preset', 'ultrafast', str(seed),
    ], check=True, capture_output=True, timeout=30)
    output_dir = tmp_path / 'published'
    worker = SimpleNamespace(abort_requested=False)
    logs = []
    service = ISOMakeMKVService(
        tools=SimpleNamespace(ffprobe=tools.ffprobe),
        inspector=SimpleNamespace(makemkv_source=lambda path: 'iso:' + path),
        worker=worker, log=lambda *args: logs.append(args), progress=lambda *_: None,
    )
    source = str(tmp_path / 'disc.iso')
    scan = service.scan_titles(source, run_makemkv=lambda *_a, **_kw: (0, [
        'TINFO:0,2,0,"Film"', 'TINFO:0,8,0,"27"', f'TINFO:0,9,0,"{reported_duration}"',
    ]))
    assert len(scan.titles) == 1
    def fake_extract(args, **_kwargs):
        shutil.copyfile(seed, Path(args[-1]) / 'Film.mkv')
        return 0, []
    result = service.extract_titles(source, [0], str(output_dir), run_makemkv=fake_extract)
    assert result.ok == expected_success, result.error
    if expected_success:
        assert (output_dir / 'Film.mkv').read_bytes() == seed.read_bytes()
        assert result.extracted_files == [str(output_dir / 'Film.mkv')]
    else:
        assert not (output_dir / 'Film.mkv').exists()
        assert 'Ausgabedauer ist nicht plausibel' in result.error
