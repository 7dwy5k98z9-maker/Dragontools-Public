"""Explicit default rules, unknown audio, persistence and actual output flags."""
from copy import deepcopy

import pytest

from dragontools.core.models import AudioStream, SubtitleStream
from dragontools.rules.subtitle_default_config import normalize_default_subtitle
from dragontools.rules.subtitle_rule_config import migrate_subtitle_rules
from dragontools.rules.subtitle_rules import compute_subtitle_plan
from dragontools.tests.test_subtitle_default_policy import rules


def audio(language):
    return AudioStream(index=1, language=language, codec='aac', channels=2,
                       forced=False, title='', bitrate=160000, default=True)


def sub(index, language, *, default=False, forced=False):
    return SubtitleStream(index=index, language=language, codec='ass', title='',
                          forced=forced, default=default)


def settings(base, *, mode='audio_differs', reference='de', priority=None):
    result = deepcopy(base)
    result['default_subtitle'] = {
        'mode': mode, 'audio_language': reference,
        'language_priority': ['de', 'en'] if priority is None else priority,
    }
    return result


def defaults(plan):
    return [s.index for s in plan.keep_streams if s.default]


@pytest.mark.parametrize('language', ['jpn', 'zh', 'eng', None, '', 'und', 'mul', 'zxx'])
def test_conditional_defaults_for_other_and_unknown_audio(rules, language):
    _, base = rules
    streams = [sub(2, 'deu'), sub(3, 'eng', default=True)]
    original = deepcopy(streams)
    plan = compute_subtitle_plan(streams, audio_streams=[audio(language)],
                                 subtitle_rules=settings(base))
    assert defaults(plan) == [2]
    assert [s.index for s in plan.external_streams if s.default] == [2]
    assert streams == original


@pytest.mark.parametrize('language', ['de', 'deu', 'ger'])
def test_conditional_matching_audio_preserves_defaults(rules, language):
    _, base = rules
    plan = compute_subtitle_plan([sub(2, 'de'), sub(3, 'en', default=True)],
                                 audio_streams=[audio(language)], subtitle_rules=settings(base))
    assert defaults(plan) == [3]


@pytest.mark.parametrize('language', ['de', 'jpn', 'und', None])
def test_always_works_for_any_audio_or_silent_video(rules, language):
    _, base = rules
    plan = compute_subtitle_plan([sub(2, 'de'), sub(3, 'en', default=True)],
                                 audio_streams=[audio(language)] if language is not None else [],
                                 subtitle_rules=settings(base, mode='always'))
    assert defaults(plan) == [2]


def test_comparison_language_and_default_ranks_are_independent_of_keep_and_audio_priorities(rules):
    sound, base = rules
    sound['language_priority'] = ['fr', 'ja']
    plan = compute_subtitle_plan([sub(2, 'de'), sub(3, 'en')], audio_streams=[audio('jpn')],
        subtitle_rules=settings(base, reference='fr', priority=['en', 'de']))
    assert defaults(plan) == [3]


def test_fallback_to_second_available_language(rules):
    _, base = rules
    plan = compute_subtitle_plan([sub(3, 'eng')], audio_streams=[audio('jpn')],
                                 subtitle_rules=settings(base))
    assert defaults(plan) == [3]


def test_rank_precedes_forced_then_regular_wins_within_same_language(rules):
    _, base = rules
    base['keep_rules'] = {'keep_forced': True, 'keep_selected_languages': True, 'keep_regular': True}
    streams = [sub(2, 'de', forced=True), sub(3, 'en'), sub(4, 'de')]
    plan = compute_subtitle_plan(streams, audio_streams=[audio('jpn')], subtitle_rules=settings(base))
    assert defaults(plan) == [4]
    assert next(s for s in plan.keep_streams if s.index == 2).forced


@pytest.mark.parametrize('priority', [[], ['fr']])
def test_no_ranked_selected_language_preserves_source_flags(rules, priority):
    _, base = rules
    plan = compute_subtitle_plan([sub(2, 'de'), sub(3, 'en', default=True)],
                                 audio_streams=[audio('jpn')], subtitle_rules=settings(base, priority=priority))
    assert defaults(plan) == [3]


def test_preserve_mode_and_manual_keep_selection_are_respected(rules):
    _, base = rules
    streams = [sub(2, 'de'), sub(3, 'en', default=True)]
    plan = compute_subtitle_plan(streams, audio_streams=[audio('jpn')],
                                 subtitle_rules=settings(base, mode='preserve'))
    assert defaults(plan) == [3]
    override = {'subtitle_mode': 'custom', 'subtitle_tracks': [{'index': 3, 'keep': True, 'burn_in': False}]}
    plan = compute_subtitle_plan(streams, audio_streams=[audio('jpn')], file_override=override,
                                 subtitle_rules=settings(base, mode='always'))
    assert [s.index for s in plan.keep_streams] == [3]
    assert defaults(plan) == [3]
    override['subtitle_tracks'] = []
    assert not compute_subtitle_plan(streams, audio_streams=[audio('jpn')], file_override=override,
                                     subtitle_rules=settings(base, mode='always')).keep_streams


def test_condition_uses_selected_default_audio_not_any_source_track(rules):
    _, base = rules
    streams = [audio('de'), audio('jpn')]
    streams[1].index = 4
    override = {'audio_mode': 'custom', 'audio_tracks': [{'index': 4, 'mode': 'auto'}]}
    plan = compute_subtitle_plan([sub(2, 'de')], audio_streams=streams, file_override=override,
                                 subtitle_rules=settings(base))
    assert defaults(plan) == [2]
    plan = compute_subtitle_plan([sub(2, 'de')], audio_streams=streams, subtitle_rules=settings(base))
    assert defaults(plan) == []


def test_audio_priority_reference_can_follow_audio_rules(rules):
    sound, base = rules
    sound['language_priority'] = ['fr', 'ja']
    plan = compute_subtitle_plan([sub(2, 'de')], audio_streams=[audio('jpn')],
        subtitle_rules=settings(base, reference='audio_priority'))
    assert defaults(plan) == [2]


@pytest.mark.parametrize('mode', ['always', 'audio_differs'])
def test_explicit_policy_reaches_dolby_vision_and_sidecar_jobs(rules, tmp_path, monkeypatch, mode):
    from types import SimpleNamespace as NS
    from dragontools.tests.test_subtitle_default_policy import media
    from dragontools.worker.dv_subtitle_mux_service import DVSubtitleMuxService
    from dragontools.worker.subtitle_sidecar_service import SubtitleSidecarService
    _, base = rules
    configured = settings(base, mode=mode, priority=['en', 'de'])
    info = media()
    info.audio_streams[0].language = 'und'
    service = DVSubtitleMuxService(ffmpeg_path='ffmpeg', subtitle_rules=configured, log=lambda *_: None)
    for jobs in (service.build_internal_jobs(info, {}), service.build_internal_mp4_jobs(info, {})):
        assert [job.default for job in jobs] == [False, True]
    configured['mp4_sidecars_enabled'] = True
    sidecars = SubtitleSidecarService(ffmpeg_path='ffmpeg', subtitle_rules=configured, log=lambda *_: None)
    monkeypatch.setattr(sidecars, '_export_target', lambda *_a, **_k: (True, None, False))
    result = sidecars.export_sidecars_result(input_path='source.mkv', output_base=tmp_path / 'Film', media_info=info)
    assert result.ok
    assert any('.en.default.srt' in path for path in result.exported_paths)
    assert not any('.de.default.' in path for path in result.exported_paths)


def test_migration_preserves_legacy_policy_until_explicitly_configured(rules):
    _, base = rules
    migrated = migrate_subtitle_rules(base)
    assert migrated['default_subtitle']['mode'] == 'legacy'
    assert migrate_subtitle_rules(migrated) == migrated
    plan = compute_subtitle_plan([sub(2, 'de')], audio_streams=[audio('und')], subtitle_rules=migrated)
    assert defaults(plan) == []


def test_config_normalizes_aliases_and_invalid_modes_and_keeps_empty_rank_list():
    config = normalize_default_subtitle({'mode': 'always', 'audio_language': 'fre',
                                        'language_priority': ['deu', 'ger', 'eng']})
    assert config == {'mode': 'always', 'audio_language': 'fr', 'language_priority': ['de', 'en']}
    assert normalize_default_subtitle({'mode': 'invalid'})['mode'] == 'preserve'
    assert normalize_default_subtitle({'mode': 'always', 'language_priority': []})['language_priority'] == []


def test_gui_checkboxes_are_mutually_exclusive_and_ranks_can_be_reordered(qtbot):
    from dragontools.gui.rules_subtitle_default_editor import _SubtitleDefaultEditor
    widget = _SubtitleDefaultEditor(settings({})['default_subtitle'], language_priority=['de', 'en'])
    qtbot.addWidget(widget)
    assert widget.audio_differs.isChecked() and not widget.always.isChecked()
    widget.always.click()
    assert widget.always.isChecked() and not widget.audio_differs.isChecked()
    assert not widget.audio_language.isEnabled()
    widget.languages.list.setCurrentRow(1)
    widget.languages._move_current(-1)
    assert widget.data()['language_priority'] == ['en', 'de']
    assert widget.languages.list.item(0).text().startswith('Rang 1: Englisch')
    assert widget.languages.list.item(1).text().startswith('Rang 2: Deutsch')
    widget.audio_differs.click()
    assert not widget.always.isChecked() and widget.audio_language.isEnabled()
    widget.audio_language.setCurrentIndex(widget.audio_language.findData('fr'))
    assert widget.data()['audio_language'] == 'fr'
    widget.audio_differs.click()
    assert widget.data()['mode'] == 'preserve'
    assert not widget.languages.isEnabled()


def test_subtitle_tab_save_reload_persists_independent_default_settings(qtbot, tmp_path, monkeypatch):
    from dragontools.gui import rules_subtitle_tab as tab_module, rules_dialog_storage as storage
    from dragontools.rules import rule_loader
    from dragontools.rules.subtitle_rule_config import DEFAULT_SUBTITLE_RULES
    monkeypatch.setattr(storage, '_rules_dir', lambda: tmp_path)
    monkeypatch.setattr(rule_loader, '_rules_dir', lambda: tmp_path)
    monkeypatch.setattr(storage, 'append_audit_event', lambda *_a, **_k: None)
    monkeypatch.setattr(storage._ar, 'reload_rules', lambda: None)
    monkeypatch.setattr(storage._rr, 'reload_rules', lambda: None)
    monkeypatch.setattr(tab_module, '_load', lambda _name: deepcopy(DEFAULT_SUBTITLE_RULES))
    tab = tab_module._SubtitleTab()
    qtbot.addWidget(tab)
    tab.default_subtitle.always.click()
    tab.default_subtitle.languages.list.setCurrentRow(1)
    tab.default_subtitle.languages._move_current(-1)
    storage._save('subtitle_rules', tab.get_data())
    loaded = storage._load('subtitle_rules')
    assert loaded['default_subtitle'] == {'mode': 'always', 'audio_language': 'de',
                                         'language_priority': ['en', 'de']}
    assert loaded['language_priority'] == ['de', 'en']
    monkeypatch.setattr(tab_module, '_load', lambda _name: loaded)
    restored = tab_module._SubtitleTab()
    qtbot.addWidget(restored)
    assert restored.get_data()['default_subtitle'] == loaded['default_subtitle']


@pytest.mark.media_integration
@pytest.mark.parametrize('container,strip_only', [('mkv', False), ('mkv', True), ('mp4', False), ('mp4', True)])
@pytest.mark.parametrize('mode', ['always', 'audio_differs'])
def test_real_output_flags_follow_explicit_rules_for_unknown_audio(rules, tmp_path, container, strip_only, mode):
    from types import SimpleNamespace as NS
    from dragontools.core.media_analyzer import analyze_media
    from dragontools.tests.ci_requirements import external_media_environment, _resolve_tool
    from dragontools.tests.test_patch12_real_media import probe, run
    from dragontools.worker.converter_subtitle_args import build_subtitle_args
    from dragontools.worker.converter_strip_subtitles import build_strip_subtitle_args
    from dragontools.worker.converter_audio_args import build_audio_args
    from dragontools.worker.media_contract import build_expected_media_contract
    from dragontools.worker.output_verifier import OutputVerifier
    environment = external_media_environment()
    if not environment.ffmpeg or not environment.ffprobe:
        pytest.skip('FFmpeg/ffprobe unavailable')
    tools = NS(ffmpeg=environment.ffmpeg, ffprobe=environment.ffprobe,
               mediainfo=_resolve_tool('DRAGONTOOLS_MEDIAINFO', 'MediaInfo.exe', 'mediainfo'))
    german = tmp_path / 'de.ass'
    german.write_text(
        '[Script Info]\nScriptType: v4.00+\n[V4+ Styles]\n'
        'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, '
        'Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, '
        'Alignment, MarginL, MarginR, MarginV, Encoding\n'
        'Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,10,1\n'
        '[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
        'Dialogue: 0,0:00:00.10,0:00:02.90,Default,,0,0,0,,Deutsch GPT\n', encoding='utf-8')
    source = tmp_path / 'source.mkv'
    run([tools.ffmpeg, '-y', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=25:duration=3',
         '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=3',
         '-i', str(german), '-map', '0:v', '-map', '1:a', '-map', '2:s',
         '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac', '-c:s', 'ass',
         '-metadata:s:a:0', 'language=und', '-metadata:s:s:0', 'language=ger',
         '-disposition:a:0', 'default', '-disposition:s:0', '0', str(source)])
    info = analyze_media(str(source), tools)
    _, base = rules
    configured = settings(base, mode=mode)
    worker = NS(subtitle_rules=configured, log=lambda *_: None,
                _logger=NS(decision=lambda *_: None, audio=lambda *_a, **_k: None))
    args = (build_strip_subtitle_args(worker, info, {}, container) if strip_only else
            build_subtitle_args(worker, str(source), info, {}, container=container, subtitle_rules=configured)[1])
    output = tmp_path / ('output.' + container)
    run([tools.ffmpeg, '-y', '-v', 'error', '-i', str(source), '-map', '0:v:0',
         '-c:v', 'copy', *build_audio_args(worker, info, {}, container), *args, str(output)])
    subtitles = [s for s in probe(output, tools)['streams'] if s['codec_type'] == 'subtitle']
    assert len(subtitles) == 1 and subtitles[0]['disposition']['default'] == 1
    contract = build_expected_media_contract(media_info=info, file_override={}, container=container,
        pipeline='standard', strip_only=strip_only, effective_codec='h264',
        effective_preserve_hdrplus=False, subtitle_rules=configured)
    result = OutputVerifier(ffprobe_path=tools.ffprobe).verify(str(output), container,
        expected_duration_ms=3000, source_has_audio=True, expected_contract=contract)
    assert result.ok, result.messages
