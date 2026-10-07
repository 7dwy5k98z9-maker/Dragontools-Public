"""Native early source checks with complete and genuinely partial DV RPUs."""
from pathlib import Path
from types import SimpleNamespace as NS
import json
import pytest
from dragontools.tests.ci_requirements import external_media_environment,_resolve_tool
from dragontools.tests.test_real_dv_hdr_integration import _DOVI_GENERATOR_CONFIG,_make_hevc,_run
from dragontools.worker.dv_source_rpu_check import SourceRpuSanityCheck
from dragontools.worker.dv_embedded_source_check import validate_embedded_source
from dragontools.worker.dv_dynamic_metadata_service import DVDynamicMetadataService
from dragontools.worker.dv_runtime_models import DVTempState
from dragontools.worker.tool_runner import run_tool

pytestmark=pytest.mark.media_integration

@pytest.mark.parametrize('partial',[False,True])
@pytest.mark.parametrize('timeline',['raw','fractional','vfr'])
def test_native_complete_and_partial_source_rpu_before_encoding(tmp_path,partial,timeline):
    env=external_media_environment()
    if not env.ffmpeg or not env.ffprobe or not env.dovi_tool:
        pytest.skip('Native DV tools unavailable')
    base=tmp_path/'base.hevc';rpu=tmp_path/'source.rpu';config=tmp_path/'rpu.json';dv=tmp_path/'dv.hevc'
    _make_hevc(ffmpeg=env.ffmpeg,target=base,frames=10)
    config.write_text(json.dumps(_DOVI_GENERATOR_CONFIG),encoding='utf-8')
    _run([env.dovi_tool,'generate','-j',str(config),'-o',str(rpu)])
    _run([env.dovi_tool,'inject-rpu','-i',str(base),'--rpu-in',str(rpu),'-o',str(dv)])
    source=dv
    if partial:
        plain=tmp_path/'plain.hevc';_make_hevc(ffmpeg=env.ffmpeg,target=plain,frames=50)
        source=tmp_path/'partial.hevc';source.write_bytes(dv.read_bytes()+plain.read_bytes())
    extracted=tmp_path/'extracted.rpu'
    _run([env.dovi_tool,'extract-rpu','-i',str(source),'-o',str(extracted)])
    if timeline!='raw':
        merge=_resolve_tool('DRAGONTOOLS_MKVMERGE','mkvmerge.exe','mkvmerge')
        if not merge:pytest.skip('Matroska tool unavailable for exact timeline fixture')
        mkv=tmp_path/'source-timeline.mkv'
        if timeline=='fractional':
            command=[merge,'-o',str(mkv),'--default-duration','0:24000/1001p',str(source)]
        else:
            timecodes=tmp_path/'vfr.txt';n=60 if partial else 10
            timecodes.write_text('# timestamp format v2\n'+'\n'.join(str(i*42+(i//3)*25) for i in range(n))+'\n',encoding='utf-8')
            command=[merge,'-o',str(mkv),'--timestamps',f'0:{timecodes}',str(source)]
        _run(command);source=mkv
    tools=NS(ffmpeg=env.ffmpeg,ffprobe=env.ffprobe,dovi_tool=env.dovi_tool)
    temp=DVTempState();logs=[]
    def capture(command,**kw):
        return run_tool(command,label='Native source check',timeout_s=60)
    dynamic=DVDynamicMetadataService.__new__(DVDynamicMetadataService);dynamic._tools=tools
    request=NS(input_path=str(source),media_info=NS(primary_video=NS(index=0,
        frame_count=(60 if partial else 10) if timeline=='raw' else None)))
    check=SourceRpuSanityCheck(tools=tools,temp_state=temp,log=lambda *a:logs.append(a))
    state=NS(request=request,files=NS(rpu_orig=extracted))
    assert check.validate(state,NS(run=capture),probe_rpu=dynamic.probe_rpu_frame_count) is (not partial)
    assert any(f'Video Frames: {60 if partial else 10}; RPU Frames: 10' in str(row) for row in logs)
    assert temp.failure_reason.startswith('SOURCE_RPU_UNUSABLE:') is partial
    temp.reset_diagnostics()
    assert validate_embedded_source(request,tools=tools,temp_state=temp,log=lambda *a:None) is (not partial)
    assert temp.failure_reason.startswith('SOURCE_RPU_UNUSABLE:') is partial
    assert source.exists() and extracted.exists()
