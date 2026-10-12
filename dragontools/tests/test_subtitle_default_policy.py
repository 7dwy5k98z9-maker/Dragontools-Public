"""Preferred subtitles follow the selected playback audio, including mux flags."""
from copy import deepcopy
from types import SimpleNamespace as NS

import pytest

from dragontools.core.models import AudioStream, MediaInfo, SubtitleStream, VideoStream
from dragontools.rules import audio_plan
from dragontools.rules.audio_rule_basics import _DEFAULT_RULES
from dragontools.rules.subtitle_rules import compute_subtitle_plan
from dragontools.worker.converter_subtitle_args import build_subtitle_args
from dragontools.worker.converter_strip_subtitles import build_strip_subtitle_args
from dragontools.worker.dv_subtitle_mux_service import DVSubtitleMuxService
from dragontools.worker.mp4_remux_plan import MP4RemuxPlanner
from dragontools.worker.subtitle_sidecar_service import SubtitleSidecarService


def audio(index=1, language='jpn', default=False):
    return AudioStream(index=index, language=language, codec='aac', channels=2,
                       forced=False, title='', bitrate=160000, default=default)


def sub(index=2, language='ger', default=False, forced=False):
    return SubtitleStream(index=index, language=language, codec='subrip',
                          forced=forced, title=language, default=default)


@pytest.fixture
def rules(monkeypatch):
    sound = deepcopy(_DEFAULT_RULES)
    sound.update(language_priority=['de', 'ja', 'en'], max_languages=1, extra_stereo=False)
    monkeypatch.setattr(audio_plan, '_load_audio_rules', lambda: sound)
    subtitles = {'language_priority': ['de', 'en'], 'max_languages': 2, 'tracks_per_language': 0,
                 'burn_in_rules': {'auto_burn_forced': False}, 'mp4_sidecars_enabled': False}
    return sound, subtitles


@pytest.mark.parametrize('language', ['ja', 'jpn', 'eng', 'zh', 'chi'])
def test_foreign_playback_sets_one_german_default_without_mutating_source(rules, language):
    _, settings = rules
    streams = [sub(2), sub(3, 'eng', default=True), sub(4, 'deu')]
    original = deepcopy(streams)
    plan = compute_subtitle_plan(streams, audio_streams=[audio(language=language)], subtitle_rules=settings)
    assert [s.index for s in plan.keep_streams if s.default] == [2]
    assert [s.index for s in plan.external_streams if s.default] == [2]
    assert streams == original


@pytest.mark.parametrize('language', ['de', 'deu', 'ger', None, '', 'und', 'mul', 'zxx'])
def test_german_or_unknown_audio_preserves_existing_defaults(rules, language):
    _, settings = rules
    streams = [sub(2), sub(3, 'eng', default=True)]
    plan = compute_subtitle_plan(streams, audio_streams=[audio(language=language)], subtitle_rules=settings)
    assert not next(s for s in plan.keep_streams if s.index == 2).default
    assert next(s for s in plan.keep_streams if s.index == 3).default


def test_regular_translation_precedes_forced_and_keeps_forced_flag(rules):
    _, settings = rules
    forced, regular = sub(2, forced=True, default=True), sub(3)
    plan = compute_subtitle_plan([forced, regular], audio_streams=[audio()], subtitle_rules=settings)
    assert next(s for s in plan.keep_streams if s.index == 2).forced
    assert not next(s for s in plan.keep_streams if s.index == 2).default
    assert next(s for s in plan.keep_streams if s.index == 3).default
    assert forced.default and not regular.default


def test_preferred_text_format_wins_over_source_bitmap_default(rules):
    _, settings = rules
    info = media()
    bitmap = sub(4, default=True)
    bitmap.codec = 'hdmv_pgs_subtitle'
    info.subtitle_streams.append(bitmap)
    worker = NS(subtitle_rules=settings, log=lambda *_: None, _logger=NS(decision=lambda *_: None))
    plan = compute_subtitle_plan(info.subtitle_streams, audio_streams=info.audio_streams, subtitle_rules=settings)
    assert [s.index for s in plan.keep_streams if s.default] == [2]
    _, args = build_subtitle_args(worker, info.path, info, {}, container='mp4', subtitle_rules=settings)
    assert args[args.index('-disposition:s:0') + 1] == 'default'


def test_custom_audio_selection_is_used_instead_of_all_source_tracks(rules):
    _, settings = rules
    original = [audio(1, 'de', True), audio(2, 'eng')]
    override = {'audio_mode': 'custom', 'audio_tracks': [{'index': 2, 'mode': 'auto'}]}
    plan = compute_subtitle_plan([sub(3)], audio_streams=original, file_override=override, subtitle_rules=settings)
    assert plan.keep_streams[0].default
    plan = compute_subtitle_plan([sub(3)], audio_streams=original, subtitle_rules=settings)
    assert not plan.keep_streams[0].default


def test_actual_default_audio_and_remux_without_language_selection(rules):
    sound, settings = rules
    sound['max_languages'] = 2
    original = [audio(1, 'de'), audio(2, 'jpn', True)]
    plan = compute_subtitle_plan([sub(3)], audio_streams=original, subtitle_rules=settings)
    assert plan.keep_streams[0].default
    sound['max_languages'] = 1
    plan = compute_subtitle_plan([sub(3)], audio_streams=original, subtitle_rules=settings)
    assert not plan.keep_streams[0].default
    plan = compute_subtitle_plan([sub(3)], audio_streams=original, subtitle_rules=settings,
                                 apply_audio_language_rules=False)
    assert plan.keep_streams[0].default


def test_mismatched_priorities_empty_audio_and_explicit_subtitle_selection(rules):
    sound, settings = rules
    sound['language_priority'] = ['en', 'de']
    assert not compute_subtitle_plan([sub()], audio_streams=[audio()], subtitle_rules=settings).keep_streams[0].default
    sound['language_priority'] = ['de', 'en']
    assert not compute_subtitle_plan([sub()], audio_streams=[], subtitle_rules=settings).keep_streams[0].default
    override = {'subtitle_mode': 'custom', 'subtitle_tracks': [{'index': 3, 'keep': True, 'burn_in': False}]}
    plan = compute_subtitle_plan([sub(2), sub(3, 'eng')], audio_streams=[audio()],
                                 subtitle_rules=settings, file_override=override)
    assert [s.index for s in plan.keep_streams] == [3] and not plan.keep_streams[0].default
    override = {'audio_mode': 'custom', 'audio_tracks': [{'index': 1, 'mode': 'drop'}]}
    assert not compute_subtitle_plan([sub()], audio_streams=[audio()], subtitle_rules=settings,
                                     file_override=override).keep_streams[0].default


def media():
    return MediaInfo(path='source.mkv', audio_streams=[audio()],
                     subtitle_streams=[sub(2), sub(3, 'eng', True)], duration_s=3,
                     video_streams=[VideoStream(index=0, codec='h264', width=160, height=90)])


@pytest.mark.parametrize('container', ['mkv', 'mp4'])
@pytest.mark.parametrize('strip_only', [False, True])
def test_standard_and_strip_args_and_validation_agree(rules, container, strip_only):
    from dragontools.worker.media_contract import build_expected_media_contract
    _, settings = rules
    info = media()
    worker = NS(subtitle_rules=settings, log=lambda *_: None, _logger=NS(decision=lambda *_: None))
    args = (build_strip_subtitle_args(worker, info, {}, container) if strip_only else
            build_subtitle_args(worker, info.path, info, {}, container=container, subtitle_rules=settings)[1])
    assert args[args.index('-disposition:s:0') + 1] == 'default'
    assert args[args.index('-disposition:s:1') + 1] == '0'
    contract = build_expected_media_contract(media_info=info, file_override={}, container=container,
        pipeline='standard', strip_only=strip_only, effective_codec='h264',
        effective_preserve_hdrplus=False, subtitle_rules=settings)
    assert [t.default for t in contract.subtitle_tracks] == [True, False]
    assert not info.subtitle_streams[0].default and info.subtitle_streams[1].default


@pytest.mark.parametrize('container', ['mkv', 'mp4'])
def test_dolby_vision_mux_jobs_keep_the_same_defaults(rules, container):
    _, settings = rules
    service = DVSubtitleMuxService(ffmpeg_path='ffmpeg', subtitle_rules=settings, log=lambda *_: None)
    jobs = (service.build_internal_jobs(media(), {}) if container == 'mkv' else service.build_internal_mp4_jobs(media(), {}))
    assert [j.default for j in jobs] == [True, False]
    assert [j.forced for j in jobs] == [False, False]


@pytest.mark.parametrize('apply_audio_rules', [False, True])
def test_mp4_remux_uses_its_actual_audio_policy(rules, apply_audio_rules):
    _, settings = rules
    info = media()
    info.audio_streams = [audio(1, 'de'), audio(4, 'jpn', True)]
    planner = MP4RemuxPlanner(ffmpeg_path='ffmpeg', apply_audio_rules=apply_audio_rules,
        export_subtitles=True, ignore_subtitles=False, subtitle_rules=settings, faststart=True,
        log=lambda *_: None, log_audio=lambda *_args, **_kwargs: None)
    args = planner.build_subtitle_args(info)
    assert args[args.index('-disposition:s:0') + 1] == ('0' if apply_audio_rules else 'default')


def test_sidecar_export_uses_default_filename_for_german_translation(rules, tmp_path, monkeypatch):
    _, settings = rules
    settings['mp4_sidecars_enabled'] = True
    service = SubtitleSidecarService(ffmpeg_path='ffmpeg', subtitle_rules=settings, log=lambda *_: None)
    targets = []
    def export(input_path, target, **kwargs):
        targets.append(target)
        return True, None, False
    monkeypatch.setattr(service, '_export_target', export)
    result = service.export_sidecars_result(input_path='source.mkv', output_base=tmp_path / 'Film', media_info=media())
    assert result.ok
    assert any('.de.default.srt' in path for path in result.exported_paths)
    assert not any('.en.default.' in path for path in result.exported_paths)


@pytest.mark.parametrize('apply_audio_rules', [False, True])
def test_remux_sidecars_respect_preserved_playback_audio(rules, tmp_path, monkeypatch, apply_audio_rules):
    from dragontools.worker.mp4_remux_sidecars import MP4RemuxSidecarService
    _, settings = rules
    settings['mp4_sidecars_enabled'] = True
    info = media()
    info.audio_streams = [audio(1, 'de'), audio(4, 'jpn', True)]
    worker = NS(apply_audio_rules=apply_audio_rules)
    service = MP4RemuxSidecarService(ffmpeg_path='ffmpeg', subtitle_rules=settings,
        log=lambda *_: None, abort_check=lambda: False, worker=worker)
    monkeypatch.setattr(SubtitleSidecarService, '_export_target', lambda *_args, **_kwargs: (True, None, False))
    result = service.export('source.mkv', str(tmp_path / 'Film'), media_info=info)
    assert result.ok
    assert any('.de.default.srt' in path for path in result.exported_paths) == (not apply_audio_rules)


@pytest.mark.media_integration
@pytest.mark.parametrize('container,strip_only', [('mkv', False), ('mkv', True), ('mp4', False), ('mp4', True)])
def test_real_ffmpeg_output_has_german_default_and_passes_validation(rules, tmp_path, container, strip_only):
    import hashlib
    from dragontools.core.media_analyzer import analyze_media
    from dragontools.tests.ci_requirements import external_media_environment, _resolve_tool
    from dragontools.tests.test_patch12_real_media import probe, run
    from dragontools.worker.media_contract import build_expected_media_contract
    from dragontools.worker.output_verifier import OutputVerifier
    from dragontools.worker.converter_audio_args import build_audio_args
    environment = external_media_environment()
    if not environment.ffmpeg or not environment.ffprobe:
        pytest.skip('FFmpeg/ffprobe unavailable')
    tools = NS(ffmpeg=environment.ffmpeg, ffprobe=environment.ffprobe,
               mediainfo=_resolve_tool('DRAGONTOOLS_MEDIAINFO', 'MediaInfo.exe', 'mediainfo'))
    german, english = tmp_path / 'de.srt', tmp_path / 'en.srt'
    german.write_text('1\n00:00:00,100 --> 00:00:02,900\nDeutscher Untertitel\n', encoding='utf-8')
    english.write_text('1\n00:00:00,100 --> 00:00:02,900\nEnglish subtitle\n', encoding='utf-8')
    source = tmp_path / 'source.mkv'
    run([tools.ffmpeg, '-y', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=25:duration=3',
         '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=3',
         '-i', str(german), '-i', str(english), '-map', '0:v', '-map', '1:a', '-map', '2:s', '-map', '3:s',
         '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac', '-c:s', 'srt',
         '-metadata:s:a:0', 'language=jpn', '-metadata:s:s:0', 'language=ger',
         '-metadata:s:s:1', 'language=eng', '-disposition:a:0', 'default',
         '-disposition:s:0', '0', '-disposition:s:1', 'default', str(source)])
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    info = analyze_media(str(source), tools)
    _, settings = rules
    worker = NS(subtitle_rules=settings, log=lambda *_: None,
                _logger=NS(decision=lambda *_: None, audio=lambda *_args, **_kwargs: None))
    args = (build_strip_subtitle_args(worker, info, {}, container) if strip_only else
            build_subtitle_args(worker, str(source), info, {}, container=container, subtitle_rules=settings)[1])
    output = tmp_path / ('output.' + container)
    run([tools.ffmpeg, '-y', '-v', 'error', '-i', str(source), '-map', '0:v:0',
         '-c:v', 'copy', *build_audio_args(worker, info, {}, container), *args, str(output)])
    subs = [s for s in probe(output, tools)['streams'] if s['codec_type'] == 'subtitle']
    assert [s['disposition']['default'] for s in subs] == [1, 0]
    contract = build_expected_media_contract(media_info=info, file_override={}, container=container,
        pipeline='standard', strip_only=strip_only, effective_codec='h264',
        effective_preserve_hdrplus=False, subtitle_rules=settings)
    result = OutputVerifier(ffprobe_path=tools.ffprobe).verify(str(output), container,
        expected_duration_ms=3000, source_has_audio=True, expected_contract=contract)
    assert result.ok, result.messages
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
