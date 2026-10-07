from __future__ import annotations

import json
import math
from types import SimpleNamespace as NS

import pytest


@pytest.mark.parametrize('seconds', [10000.1, 14400, 86400])
def test_mediainfo_json_duration_is_seconds_for_long_media(seconds):
    from dragontools.core.media_analyzer_video_streams import _build_video_streams
    from dragontools.core.mediainfo_details import build_mediainfo_display_details
    track={'@type':'Video','Format':'HEVC','Duration':str(seconds),'StreamSize':'1000000'}
    video=_build_video_streams([track],[],{},[])[0]
    assert video.duration_s==seconds
    assert video.bitrate==round(8_000_000/seconds)
    details=build_mediainfo_display_details('missing.mkv',payload={'media':{'track':[{'@type':'General','Duration':str(seconds)}]}})
    assert f'({seconds:.1f}s)' in dict(details.overview_rows)['Dauer']


@pytest.mark.parametrize('value',['inf','nan',float('inf')])
def test_nonfinite_media_seconds_are_unknown(value):
    from dragontools.core.media_metadata import _parse_seconds_value
    assert _parse_seconds_value(value) is None


@pytest.mark.parametrize('index',['++2','²',True,'2.9'])
def test_invalid_stream_indices_are_rejected_without_crash(index):
    from dragontools.core.media_analyzer_audio_streams import _build_audio_streams
    assert _build_audio_streams([],[{'index':index,'codec_name':'aac'}])[0].index<0


def test_cross_tool_pairing_uses_container_identity_not_list_position():
    from dragontools.core.media_analyzer_audio_streams import _build_audio_streams
    tracks=[{'ID':'20','Format':'AAC','Language':'German','Default':'Yes'},
            {'ID':'10','Format':'AAC','Language':'English','Default':'No'}]
    probe=[{'index':3,'id':'0xa','codec_name':'aac'}, {'index':7,'id':'0x14','codec_name':'aac'}]
    result=_build_audio_streams(tracks,probe,[])
    assert [(s.index,s.language,s.default) for s in result]==[(3,'english',False),(7,'de',True)]


def test_mediainfo_only_extras_are_not_added_to_successful_probe_topology():
    from dragontools.core.media_analyzer_audio_streams import _build_audio_streams
    result=_build_audio_streams([{'Format':'AAC'},{'Format':'AC-3'}],[{'index':2,'codec_name':'aac'}],[])
    assert len(result)==1 and result[0].index==2


def test_foreign_video_metadata_does_not_contaminate_primary():
    from dragontools.core.media_analyzer_video_streams import _build_video_streams
    from dragontools.core.media_analyzer_metadata import collect_video_metadata
    mi=[{'Format':'AVC','ID':'99','Width':'640','Height':'480','HDR_Format':'Dolby Vision, Profile 9'},
        {'Format':'HEVC','ID':'4','Width':'1920','Height':'1080','transfer_characteristics':'BT.709'}]
    fp=[{'index':5,'id':'0x4','codec_name':'hevc','width':1920,'height':1080,'color_transfer':'bt709'}]
    videos=_build_video_streams(mi,fp,{},[])
    metadata=collect_video_metadata(videos,mi,fp,[])
    assert len(videos)==1 and videos[0].width==1920
    assert not videos[0].has_dolby_vision and not metadata.dv_info['dolby_vision']
    assert metadata.transfer_characteristics=='BT.709'


@pytest.mark.parametrize('streams',[[],[{'index':0,'codec_type':'video','codec_name':'hevc'},
                                     {'index':0,'codec_type':'audio','codec_name':'aac'}]])
def test_empty_or_duplicate_probe_mappings_are_untrusted(monkeypatch,streams):
    from dragontools.core import media_analyzer as module
    monkeypatch.setattr(module,'_analysis_payloads',lambda *a:({}, {'streams':streams},'ffprobe',[]))
    info=module.analyze_media('missing.mkv',NS())
    assert not info.ffmpeg_stream_indices_trusted


def test_valid_declared_language_wins_over_title():
    from dragontools.core.media_analyzer_audio_streams import _build_audio_streams
    stream=_build_audio_streams([],[{'index':2,'codec_name':'aac','tags':{'language':'jpn','title':'German commentary'}}])[0]
    assert stream.language=='jpn'


def test_regional_language_matches_language_rules():
    from dragontools.core.lang_codes import language_matches,canonical_lang,mkv_language_tags
    assert canonical_lang('en-US')=='en'
    assert language_matches('en-US','eng')
    assert mkv_language_tags('en-US')==('eng','en-us')


def test_source_duration_string_false_attached_pic_keeps_real_video():
    from dragontools.core.media_duration import source_duration
    assert source_duration({'format':{'duration':100},'streams':[{'index':0,'codec_type':'video','duration':90,'disposition':{'attached_pic':'0'}}]})==90


def test_duration_ts_uses_time_base_when_seconds_are_absent():
    from dragontools.core.media_duration import stream_duration
    assert stream_duration({'duration_ts':900000,'time_base':'1/90000'})==10


@pytest.mark.parametrize('probability',[float('nan'),float('inf'),'broken'])
def test_invalid_language_confidence_cannot_authorize_metadata_change(probability):
    from dragontools.core.language_detection import combine_language_evidence,LanguageEvidence
    result=combine_language_evidence([LanguageEvidence('de',probability)])
    assert not result.accepted and math.isfinite(result.probability)


def test_unknown_language_samples_do_not_disappear_from_consensus():
    from dragontools.core.language_detection import combine_language_evidence,LanguageEvidence
    result=combine_language_evidence([LanguageEvidence('de',.99),LanguageEvidence('und',0),LanguageEvidence('',0)])
    assert not result.accepted and result.probability==pytest.approx(.33)


@pytest.mark.parametrize('payload',['[]','{"format":"broken"}','{"format":{"duration":"inf"}}'])
def test_language_duration_probe_invalid_shape_fails_softly(monkeypatch,payload):
    from dragontools.worker import media_stream_language_service as module
    monkeypatch.setattr(module,'run_tool',lambda *a,**k:NS(returncode=0,stdout=payload))
    service=module.MediaStreamLanguageService(settings=NS(value=lambda key,default,**kwargs:default),tools=NS())
    assert service._probe_duration('missing')==0


@pytest.mark.parametrize('ordinal',[True,1.9,'1.5','bad'])
def test_invalid_mkv_typed_ordinal_never_edits_another_track(monkeypatch,ordinal):
    from dragontools.core import mkv_track_metadata as module
    calls=[]
    monkeypatch.setattr(module,'tool_available',lambda *a:True)
    monkeypatch.setattr(module,'run_analysis_tool',lambda *a,**k:calls.append(a))
    ok,_=module.apply_mkv_track_metadata('movie.mkv',stream_type='audio',ordinal=ordinal,mkvpropedit_path='mkvpropedit',title='new')
    assert not ok and calls==[]


@pytest.mark.parametrize('applied',[False,True])
def test_track_edit_verifies_staged_metadata_before_commit(tmp_path,monkeypatch,applied):
    from dataclasses import replace
    from dragontools.tests.test_patch_i_language_detection import _stream_issue,_Tools
    from dragontools.worker import media_stream_metadata_guard as module
    issue=replace(_stream_issue(tmp_path),stream_ordinal=1)
    before=module.file_signature(issue.path)
    changed=False
    def probe(command,**kwargs):
        staged=command[-1]!=issue.path
        language='de' if staged and changed and applied else 'und'
        stream={'index':2,'codec_type':'audio','codec_name':'eac3','channels':6,
                'tags':{'language':language,'title':''},'disposition':{'forced':0}}
        return NS(returncode=0,aborted=False,stdout=json.dumps({'streams':[stream]}))
    def edit(path,**kwargs):
        nonlocal changed
        changed=True
        return True,'edited'
    monkeypatch.setattr(module,'run_tool',probe)
    monkeypatch.setattr(module,'apply_mkv_track_metadata',edit)
    ok,_=module.edit_queued_track(issue,tools=_Tools(),language='de')
    assert ok is applied
    if not applied:assert module.file_signature(issue.path)==before


def test_audio_extraction_failures_remain_in_language_consensus(tmp_path,monkeypatch):
    from dragontools.tests.test_patch_i_language_detection import _stream_issue,_Tools,_Settings
    from dragontools.worker import media_stream_language_service as module
    from dragontools.core.language_detection import LanguageEvidence
    service=module.MediaStreamLanguageService(settings=_Settings(),tools=_Tools())
    monkeypatch.setattr(module.FasterWhisperLanguageDetector,'available',lambda:True)
    monkeypatch.setattr(service,'_whisper_detector',lambda:NS(detect_file=lambda _:LanguageEvidence('de',.99)))
    successes=iter([True,False,False])
    monkeypatch.setattr(service,'_extract_audio_sample',lambda *a:next(successes))
    result=service.detect(_stream_issue(tmp_path))
    assert not result.accepted and result.probability==pytest.approx(.33)


def test_converter_analysis_rejects_audio_only_input(monkeypatch):
    from dragontools.worker import media_analysis_service as module
    info=NS(ffmpeg_stream_indices_trusted=True,primary_video=None,analysis_warnings=[])
    monkeypatch.setattr(module,'analyze_media',lambda *a:info)
    service=module.MediaAnalysisService(tools=NS(),probe_duration_ms=lambda _:1000,log=lambda *a:None)
    with pytest.raises(RuntimeError,match='Videospur'):
        service.analyze('audio.mka')


@pytest.mark.parametrize('burn',['none','image'])
def test_standard_filter_planning_pins_analyzed_primary_global_index(burn):
    from dragontools.worker.converter_stream_args import ConverterStreamArgsHelper
    primary=NS(index=3)
    sub=NS(index=7,codec='hdmv_pgs_subtitle')
    media=NS(primary_video=primary,subtitle_streams=[sub])
    helper=ConverterStreamArgsHelper(NS())
    args=helper.build_vf_args('cover.mkv','out.mkv',media,sub if burn=='image' else None,[])
    if burn=='none':assert args==['-map','0:3']
    else:assert '[0:3][0:s:0]' in args[args.index('-filter_complex')+1]


def test_strip_copy_pins_analyzed_primary_global_index(monkeypatch):
    from dragontools.worker.converter_strip import ConverterStripHelper
    from dragontools.worker import converter_strip as module
    captured=[]
    worker=NS(log=lambda *a:None,tools=NS(ffmpeg='ffmpeg'),_progress=NS(run=lambda command:captured.append(command) or 0))
    monkeypatch.setattr(module,'build_strip_audio_args',lambda *a:([],[]))
    monkeypatch.setattr(module,'build_strip_subtitle_args',lambda *a:[])
    monkeypatch.setattr(module,'export_strip_sidecars',lambda *a,**k:(True,[]))
    assert ConverterStripHelper(worker).strip_only('cover.mkv','out.mkv',NS(primary_video=NS(index=3)))
    assert captured and captured[0][captured[0].index('-map')+1]=='0:3'


@pytest.mark.parametrize('field',['Width','FileSize'])
def test_mediainfo_display_handles_nonfinite_numeric_fields(field):
    from dragontools.core.mediainfo_details import build_mediainfo_display_details
    payload={'media':{'track':[{'@type':'General',field:'inf'},{'@type':'Video',field:'inf'}]}}
    details=build_mediainfo_display_details('missing.mkv',payload=payload)
    assert details.overview_rows
    assert dict(details.overview_rows)['Dateigröße']=='—'
    assert dict(details.video_rows)['Auflösung']=='—'


def test_invalid_mediainfo_bitrate_does_not_override_healthy_probe():
    from dragontools.core.media_analyzer_audio_streams import _build_audio_streams
    audio=_build_audio_streams([{'Format':'AAC','BitRate':'inf'}],[{'index':2,'codec_name':'aac','bit_rate':128000}])[0]
    assert audio.bitrate==128000
