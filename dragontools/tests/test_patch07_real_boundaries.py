"""Small generated media proves the contracts with real installed CLI tools."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from dragontools.tests.ci_requirements import _resolve_tool, external_media_environment
from dragontools.tests.test_real_dv_hdr_integration import _DOVI_GENERATOR_CONFIG, _make_hevc, _run, _sha256
from dragontools.tests.test_review07_dolby_vision_core import _encoder
from dragontools.worker.dv_command_runner import DVCommandRunner
from dragontools.worker.dv_encode_command import build_dv_encode_command
from dragontools.worker.dv_level5_editor import DVLevel5Editor
from dragontools.worker.dv_pipeline_context import DVWorkFiles
from dragontools.worker.dv_rpu_service import DVRpuService
from dragontools.worker.dv_runtime_models import DVTempState
from dragontools.worker.dv_video_stage_service import DVVideoStageService

pytestmark = pytest.mark.dv_hdr_integration


@pytest.fixture
def env():
    value = external_media_environment()
    if not value.ffmpeg or not value.ffprobe or not value.dovi_tool:
        pytest.skip('FFmpeg/ffprobe/dovi_tool unavailable')
    return value


def _runner():
    return DVCommandRunner(log=lambda *_: None, verbose_log=lambda *_: None,
        no_window_kwargs=lambda: {}, temp_state=DVTempState())


def _generate(env, root: Path, luminance: int):
    config = deepcopy(_DOVI_GENERATOR_CONFIG)
    config['level6']['max_display_mastering_luminance'] = luminance
    source = root / f'rpu_{luminance}.json'
    target = source.with_suffix('.rpu')
    source.write_text(json.dumps(config), encoding='utf-8')
    _run([env.dovi_tool, 'generate', '-j', str(source), '-o', str(target)])
    return target


def test_real_multi_video_matroska_extracts_selected_rpu_not_first_track(tmp_path, env):
    mkvmerge = _resolve_tool('DRAGONTOOLS_MKVMERGE', 'mkvmerge', 'mkvmerge.exe')
    if not mkvmerge:
        pytest.skip('mkvmerge unavailable')
    base = tmp_path / 'base.hevc'
    _make_hevc(ffmpeg=env.ffmpeg, target=base, frames=10)
    rpus = [_generate(env, tmp_path, luminance) for luminance in (1000, 2000)]
    injected = []
    for i, rpu in enumerate(rpus):
        target = tmp_path / f'dv{i}.hevc'
        _run([env.dovi_tool, 'inject-rpu', '-i', str(base), '--rpu-in', str(rpu), '-o', str(target)])
        injected.append(target)
    source = tmp_path / 'zwei Videospuren ä.mkv'
    # Raw HEVC with B pictures has no container timestamps. MKVToolNix
    # reconstructs them; FFmpeg stream-copy cannot invent the missing DTS.
    _run([mkvmerge, '-o', str(source), '--default-duration', '0:24p', str(injected[0]),
        '--default-duration', '0:24p', str(injected[1])])
    first, second = SimpleNamespace(index=0), SimpleNamespace(index=1)
    files = DVWorkFiles.create(tmp_path)
    request = SimpleNamespace(input_path=str(source), profile_major=8,
        media_info=SimpleNamespace(dv_profile_major=8, primary_video=second, video_streams=[first, second]))
    service = DVVideoStageService(tools=SimpleNamespace(ffmpeg=env.ffmpeg, dovi_tool=env.dovi_tool, mkvmerge=mkvmerge),
        encoder_config=_encoder(), progress_runner=None, temp_state=DVTempState(), hdr10plus_service=None,
        rpu_service=DVRpuService(dovi_tool_path=env.dovi_tool, log=lambda *_: None), failure_recovery=None,
        log=lambda *_: None, verbose_log=lambda *_: None, assert_nonempty_file=lambda p, _: p.is_file() and p.stat().st_size > 0,
        clear_burn_sub_tmp=lambda: None)
    assert service.extract_rpu(SimpleNamespace(request=request, files=files), _runner())
    assert _sha256(files.rpu_orig) == _sha256(rpus[1])
    assert _sha256(files.rpu_orig) != _sha256(rpus[0])


def test_real_physical_crop_clears_level5_and_keeps_all_ten_rpus(tmp_path, env):
    source = _generate(env, tmp_path, 1000)
    config, nonzero = tmp_path / 'nonzero.json', tmp_path / 'nonzero.rpu'
    config.write_text(json.dumps({'active_area': {'presets': [{'id': 0, 'left': 0, 'right': 0, 'top': 4, 'bottom': 4}], 'edits': {'all': 0}}}), encoding='utf-8')
    _run([env.dovi_tool, 'editor', '-i', str(source), '-j', str(config), '-o', str(nonzero)])
    final = tmp_path / 'cropped.rpu'
    editor = DVLevel5Editor(dovi_tool_path=env.dovi_tool, log=lambda *_: None)
    result = editor.resolve_rpu_for_crop(_runner().run, crop='crop=128:64:0:4',
        media_info=SimpleNamespace(primary_video=SimpleNamespace(width=128, height=72)),
        rpu_orig=nonzero, rpu_final=final, edit_json=tmp_path / 'crop.json',
        save_failure_artifacts=lambda *_: pytest.fail('Real Level-5 edit failed'))
    assert result == final
    summary = _run([env.dovi_tool, 'info', '-s', str(final)])
    assert 'Frames: 10' in summary.combined_output
    assert _sha256(final) != _sha256(nonzero)


def test_real_cpu_dv_encode_accepts_global_indices_and_two_input_graph(tmp_path, env):
    source = tmp_path / 'two.mkv'
    _run([env.ffmpeg, '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=red:s=64x64:r=24:d=0.25',
        '-f', 'lavfi', '-i', 'color=c=black:s=64x64:r=24:d=0.25', '-map', '0:v', '-map', '1:v', '-c:v', 'ffv1', str(source)])
    output = tmp_path / 'encoded.hevc'
    plan = build_dv_encode_command(ffmpeg_path=env.ffmpeg, encoder_config=_encoder(), input_path=str(source), output_hevc=output,
        vf_args=['-filter_complex', '[0:1][0:0]overlay[out]', '-map', '[out]'], profile_major=8, source_stream_index=1)
    result = _run(plan.command)
    assert 'frame=6' in result.stdout
    probe = _run([env.ffprobe, '-v', 'error', '-show_entries', 'stream=codec_name,pix_fmt,width,height', '-of', 'json', str(output)])
    stream = json.loads(probe.stdout)['streams'][0]
    assert (stream['codec_name'], stream['pix_fmt'], stream['width'], stream['height']) == ('hevc', 'yuv420p10le', 64, 64)
