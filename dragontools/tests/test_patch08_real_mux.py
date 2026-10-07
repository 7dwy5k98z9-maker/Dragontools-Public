"""Real final-container proof for generated DV plus HDR10+ metadata."""
import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from dragontools.tests.ci_requirements import external_media_environment
from dragontools.tests.test_real_dv_hdr_integration import _make_hevc, _run, _DOVI_GENERATOR_CONFIG, _HDR10PLUS_SINGLE_FRAME
from dragontools.worker.dv_command_runner import DVCommandRunner
from dragontools.worker.dv_final_metadata_verifier import DVFinalMetadataVerifier
from dragontools.worker.dv_mkv_muxer import DVMKVMuxer
from dragontools.worker.dv_mp4box_muxer import DVMP4BoxMuxer
from dragontools.worker.dv_pipeline_context import DVWorkFiles
from dragontools.worker.dv_rpu_service import DVRpuService
from dragontools.worker.dv_runtime_models import DVTempState
from dragontools.worker.hdr10plus_bitstream_service import HDR10PlusBitstreamService


pytestmark = pytest.mark.dv_hdr_integration


@pytest.mark.parametrize('container', ['mkv', 'mp4'])
def test_real_final_mux_preserves_both_dynamic_metadata_contents(tmp_path, container):
    env = external_media_environment()
    assert not env.missing
    mkvmerge = os.environ['DRAGONTOOLS_MKVMERGE']
    files = DVWorkFiles.create(tmp_path)
    _make_hevc(ffmpeg=env.ffmpeg, target=files.enc_hevc, frames=10)
    config = dict(_DOVI_GENERATOR_CONFIG, length=10)
    config_path = tmp_path / 'dovi.json'
    config_path.write_text(json.dumps(config), encoding='utf-8')
    _run([env.dovi_tool, 'generate', '-j', str(config_path), '-o', str(files.rpu_orig)])
    metadata = deepcopy(_HDR10PLUS_SINGLE_FRAME)
    scene = metadata['SceneInfo'][0]
    metadata['SceneInfo'] = [dict(deepcopy(scene), SceneFrameIndex=index, SequenceFrameIndex=index) for index in range(10)]
    metadata['SceneInfoSummary']['SceneFrameNumbers'] = [10]
    files.hdr10plus_json.write_text(json.dumps(metadata), encoding='utf-8')
    logs = []
    tools = SimpleNamespace(ffmpeg=env.ffmpeg, ffprobe=env.ffprobe, dovi_tool=env.dovi_tool, hdr10plus_tool=env.hdr10plus_tool)
    runner = DVCommandRunner(log=lambda *args: logs.append(args), verbose_log=lambda *_: None, no_window_kwargs=lambda: {}, temp_state=DVTempState())
    hdr = HDR10PlusBitstreamService(hdr10plus_tool_path=env.hdr10plus_tool, log=lambda *args: logs.append(args))
    rpu = DVRpuService(dovi_tool_path=env.dovi_tool, log=lambda *args: logs.append(args))
    run = runner.adapter(timeout=120, label='real metadata injection/mux')
    assert hdr.inject_metadata(run, input_hevc=files.enc_hevc, metadata_json=files.hdr10plus_json, output_hevc=files.hdr10plus_hevc)
    assert rpu.inject_rpu(run, input_hevc=files.hdr10plus_hevc, input_rpu=files.rpu_orig, output_hevc=files.injected)
    output = tmp_path / ('Film Überprüfung.' + container)
    mux = DVMKVMuxer(mkvmerge_path=mkvmerge, audio_track_name=lambda _: '') if container == 'mkv' else DVMP4BoxMuxer(mp4box_path=env.mp4box, audio_track_name=lambda _: '')
    assert mux.mux_final_output(run, output_path=str(output), injected_hevc=files.injected, mux_tracks=[]), logs
    state = SimpleNamespace(request=SimpleNamespace(output_path=str(output), container=container, profile_major=8, requires_hdr10plus=True), files=files, rpu_to_use=files.rpu_orig, effective_crop=None, verified_dolby_vision=False, verified_hdr10plus=False, verified_dv_crop_alignment=False)
    verifier = DVFinalMetadataVerifier(tools=tools, temp_state=DVTempState(), rpu_service=rpu, hdr10plus_service=hdr, log=lambda *args: logs.append(args), verbose_log=lambda *_: None, assert_nonempty_file=lambda p, _: p.is_file() and p.stat().st_size > 0)
    # MediaInfo presence must still invoke the real extract-and-compare path.
    signals = SimpleNamespace(conclusive=True, dolby_vision=True, dolby_vision_profile='8.1', hdr10plus=True)
    digest = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
    assert verifier.verify(state, runner, inspect_dynamic_hdr=lambda *_: signals, verify_fallback=lambda s, r, **kw: verifier.verify_fallback(s, r, sha256_file=digest, **kw))
    assert state.verified_hdr10plus and state.final_rpu_present and state.final_rpu_matches_injected
    probe = _run([env.ffprobe, '-v', 'error', '-show_entries', 'stream=codec_type', '-of', 'json', str(output)])
    assert [stream['codec_type'] for stream in json.loads(probe.stdout)['streams']] == ['video']
