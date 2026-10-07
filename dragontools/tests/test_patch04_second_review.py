from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from dragontools.core.models import AudioStream, MediaInfo, SubtitleStream, VideoStream, normalize_override_dict
from dragontools.core.encoder_profile_override import effective_encoder_settings
from dragontools.core.rules_preview import build_rules_preview
from dragontools.rules.move_rules import find_series_dir_candidates, resolve_series_root_dir


def _media(*, dv=False, hdrplus=False):
    return MediaInfo(path='Show.S01E01.mkv',
        video_streams=[VideoStream(index=0, codec='hevc', width=1920, height=1080)],
        audio_streams=[AudioStream(index=1, language='de', forced=False, title='', codec='aac', channels=2, bitrate=256000)],
        subtitle_streams=[SubtitleStream(index=2, language='de', forced=False, title='', codec='subrip')],
        dolby_vision=dv, has_hdr10plus=hdrplus, is_hdr=dv or hdrplus)


def _effective(override=None, options=None):
    return effective_encoder_settings(default_codec='h265', default_crf=23,
        default_preset='medium', default_scale_mode='original',
        default_encoder_options=options or {'encoder': 'cpu'}, file_override=override)


def test_missing_requested_year_never_uses_other_series_edition(tmp_path):
    (tmp_path / 'Ranma ½ (1989)').mkdir()
    assert find_series_dir_candidates(str(tmp_path), 'Ranma ½ (2024)') == []
    assert resolve_series_root_dir(str(tmp_path), 'Ranma ½ (2024)') == str(tmp_path / 'Ranma ½ (2024)')


def test_explicit_metadata_year_beats_old_name_suffix(tmp_path):
    for year in (1989, 2024):
        (tmp_path / f'Ranma ½ ({year})').mkdir()
    assert find_series_dir_candidates(str(tmp_path), 'Ranma ½ (1989)', year=2024) == [str(tmp_path / 'Ranma ½ (2024)')]


def test_known_year_lookup_does_not_fall_back_to_wrong_raw_folder(tmp_path):
    from dragontools.gui.preflight_metadata_series import resolve_series_metadata
    from dragontools.gui.preflight_metadata_common import MetadataLookupCache
    (tmp_path / 'Ranma ½ (1989)').mkdir()
    suggestion = SimpleNamespace(first_air_year=2024, folder_name='Ranma ½ (2024)')
    result = resolve_series_metadata({'series_name': 'Ranma ½', 'year': 2024, 'base': str(tmp_path)},
        settings=object(), online_enabled=True, cache=MetadataLookupCache(),
        find_series_dir_from_settings=lambda *args, **kwargs: None,
        find_series_dir_candidates=find_series_dir_candidates,
        suggest_series_metadata_for_name=lambda *args, **kwargs: suggestion)
    assert result is suggestion


def test_new_metadata_series_folder_contains_year(qapp, tmp_path):
    from dragontools.gui.preflight_series_widget import SeriesGroupWidget
    name = 'Die sieben Ritter des Königreichs der Marronniers'
    source = str(tmp_path / f'{name}.S01E01.mkv')
    widget = SeriesGroupWidget(name, [{'path': source, 'season': 1}], str(tmp_path), None)
    widget.apply_online_metadata_suggestion(SimpleNamespace(first_air_year=2026, folder_name=f'{name} (2026)'))
    assert widget.get_planned_targets()[source] == str(tmp_path / f'{name} (2026)' / 'Staffel 01')
    widget.close()


@pytest.mark.parametrize('mode', ['encode', 'remux'])
def test_selected_series_target_survives_result_and_move_routing(qapp, tmp_path, monkeypatch, mode):
    from dragontools.gui.preflight_series_widget import SeriesGroupWidget
    from dragontools.gui.conversion_result_service import ConversionResultService
    from dragontools.gui.conversion_session_state import ConversionSessionState
    from dragontools.core.move_routing import MoveRouter
    old = tmp_path / 'Ranma ½ (1989)'
    chosen = tmp_path / 'Ranma ½ (2024)'
    old.mkdir(); chosen.mkdir()
    source = str(tmp_path / 'Ranma ½.S01E01.mkv')
    output = str(tmp_path / f'Ranma ½.S01E01_{mode}.mp4')
    widget = SeriesGroupWidget('Ranma ½', [{'path': source, 'season': 1, 'year': 2024}], str(tmp_path), None)
    widget.apply_existing_series_dir(str(chosen), str(tmp_path), 'Ranma ½')
    state = ConversionSessionState()
    state.planned_targets = widget.get_planned_targets()
    state.file_overrides[source] = {'encoder_profile': {'key': 'selected'}}
    state.thread = SimpleNamespace(_session_state=SimpleNamespace(sidecar_outputs={}, postprocess_outputs={}, failure_details={}))
    service = ConversionResultService(state=state, ui=SimpleNamespace(file_list=object()),
        log=lambda *args: None, start_move=lambda *args: None, set_start_enabled=lambda *args: None,
        set_queue_edit=lambda *args: None, refresh_queue=lambda: None, clear=lambda: None,
        confirm_shutdown=lambda: None)
    monkeypatch.setattr(service, '_set_file_list_item_text', lambda *args: None)
    service.on_file_result(source, output, '✅')
    target = str(chosen / 'Staffel 01')
    assert state.planned_targets[output] == target
    assert source not in state.planned_targets
    router = MoveRouter(tv_path=str(tmp_path), anime_path='', filme_path='', all_video_files=[],
        planned_target_for=state.planned_targets.get,
        ask=lambda *args: pytest.fail('authoritative planned target must not trigger another choice'), log=lambda *args: None)
    assert router.route(output) == target
    assert state.file_overrides[output]['encoder_profile']['key'] == 'selected'
    widget.close()


def test_invalid_authoritative_target_fails_without_replanning(tmp_path):
    from dragontools.core.move_routing import MoveRouter
    source = str(tmp_path / 'Ranma ½.S01E01.mkv')
    router = MoveRouter(tv_path=str(tmp_path), anime_path='', filme_path='', all_video_files=[],
        planned_target_for=lambda _: str(tmp_path.parent / 'foreign' / 'Staffel 01'),
        ask=lambda *args: pytest.fail('must not silently replan'), log=lambda *args: None)
    assert router.route(source) == ''


def test_planned_season_beats_filename_during_rebase():
    from dragontools.core.planned_target_edit import rebase_series_target
    assert rebase_series_target('Show.S01E01.mkv', r'D:\TV\Show\Staffel 04', r'D:\TV\New') == r'D:\TV\New\Staffel 04'


@pytest.mark.parametrize('key', ['encoder_profile', 'encoder_override'])
def test_normalized_per_file_options_are_deeply_isolated(key):
    raw = {key: {'codec': 'h265', 'encoder_options': {'model': {'name': 'original'}}}}
    normalized = normalize_override_dict(raw)
    normalized[key]['encoder_options']['model']['name'] = 'changed'
    assert raw[key]['encoder_options']['model']['name'] == 'original'


def test_effective_options_are_deeply_isolated():
    options = {'encoder': 'cpu', 'model': {'name': 'original'}}
    result = _effective(options=options)
    result['encoder_options']['model']['name'] = 'changed'
    assert options['model']['name'] == 'original'


def test_encoder_backend_switch_does_not_inherit_foreign_options():
    result = _effective({'encoder_override': {'codec': 'h265', 'encoder': 'nvenc', 'quality': 25}},
        {'encoder': 'cpu', 'aq_strength': '1.0', 'bf': 8, 'psy_rd': '2.0', 'autocrop_strength': 24})
    assert 'aq_strength' not in result['encoder_options']
    assert 'bf' not in result['encoder_options']
    assert 'psy_rd' not in result['encoder_options']
    assert result['encoder_options']['autocrop_strength'] == 24


def test_direct_effective_sdr_hdr_false_string_remains_false():
    assert _effective({'sdr_hdr': 'false'})['encoder_options']['sdr_hdr_enabled'] is False


def test_current_custom_empty_audio_list_is_authoritative():
    from dragontools.rules.audio_plan import compute_audio_track_plan
    assert compute_audio_track_plan(_media().audio_streams,
        {'audio_mode': 'custom', 'audio_tracks': []}, 'mkv', rules={}) == []


def test_legacy_subtitle_migration_keeps_policy_on_repeated_normalization():
    from dragontools.rules.subtitle_rules import migrate_subtitle_rules, compute_subtitle_plan
    raw = {'keep_rules': {'keep_all_german': True, 'keep_english_fallback': False},
        'burn_in_rules': {'auto_burn_forced': False}}
    first = migrate_subtitle_rules(raw)
    second = migrate_subtitle_rules(first)
    assert second == first
    streams = [SubtitleStream(index=2, language='en', forced=False, title='', codec='subrip')]
    assert compute_subtitle_plan(streams, subtitle_rules=first).keep_streams == ()


def test_move_migration_default_trees_are_isolated():
    from dragontools.rules.move_rule_config import migrate_move_rules, _DEFAULT_MOVE_RULES
    original = deepcopy(_DEFAULT_MOVE_RULES)
    migrated = migrate_move_rules({})
    migrated['series_patterns'].append('changed')
    migrated['collection_rules'].append({'changed': True})
    try:
        assert _DEFAULT_MOVE_RULES == original
    finally:
        _DEFAULT_MOVE_RULES.clear(); _DEFAULT_MOVE_RULES.update(original)


@pytest.mark.parametrize('container,sidecars', [('mkv', False), ('mp4', False), ('mp4', True)])
def test_dv_subtitle_preview_matches_actual_mux_selection(container, sidecars):
    from dragontools.worker.dv_subtitle_mux_service import DVSubtitleMuxService
    mi = _media(dv=True)
    rules = {'language_priority': ['de'], 'burn_in_rules': {'auto_burn_forced': False}, 'mp4_sidecars_enabled': sidecars}
    preview = build_rules_preview(mi.path, media_info=mi, dv_container=container, subtitle_rules=rules)
    mux = DVSubtitleMuxService(ffmpeg_path='ffmpeg', subtitle_rules=rules, log=lambda *args: None)
    jobs = mux.build_internal_jobs(mi, None) if container == 'mkv' else mux.build_internal_mp4_jobs(mi, None)
    assert [s['index'] for s in preview['subtitles']['stream_copy_candidates']] == [j.stream_index for j in jobs]


def test_dv_combined_hdr10plus_preservation_is_reported():
    mi = _media(dv=True, hdrplus=True)
    preview = build_rules_preview(mi.path, media_info=mi)
    assert preview['hdr10plus_preserved'] is True


def test_pgs_sidecar_policy_is_shared_by_preview_and_output_contract():
    from dragontools.worker.media_contract import build_expected_media_contract
    mi = _media()
    mi.subtitle_streams[0].codec = 'hdmv_pgs_subtitle'
    rules = {'language_priority': ['de'], 'burn_in_rules': {'auto_burn_forced': False}, 'pgs_original_storage': 'sidecar'}
    preview = build_rules_preview(mi.path, media_info=mi, subtitle_rules=rules)
    contract = build_expected_media_contract(media_info=mi, file_override=None, container='mkv',
        pipeline='standard', strip_only=False, effective_codec='h265', effective_preserve_hdrplus=False,
        subtitle_rules=rules, effective_scale_mode='original', crop_filter=None)
    assert preview['subtitles']['copy_candidate_count'] == len(contract.subtitle_tracks) == 0
    assert [s['index'] for s in preview['subtitles']['native_sidecar_candidates']] == [2]


@pytest.mark.parametrize('container', ['mkv', 'mp4'])
def test_strip_preview_keeps_burn_candidate_as_subtitle(container):
    mi = _media()
    mi.subtitle_streams[0].forced = True
    rules = {'language_priority': ['de'], 'mp4_sidecars_enabled': False, 'burn_in_rules': {'ask_if_ambiguous': False}}
    preview = build_rules_preview(mi.path, media_info=mi, file_override={'processing_mode': 'strip_only'},
        standard_container=container, subtitle_rules=rules)
    assert preview['subtitles']['burn_in'] is False
    assert [s['index'] for s in preview['subtitles']['stream_copy_candidates']] == [2]


def test_strip_preview_never_promises_new_hdr10plus_generation():
    mi = _media()
    mi.is_hdr = True
    mi.video_streams[0].color_transfer = 'smpte2084'
    mi.video_streams[0].color_primaries = 'bt2020'
    preview = build_rules_preview(mi.path, media_info=mi, file_override={'processing_mode': 'strip_only'},
        hdr10plus_generator_enabled=True, hdr10plus_generator_available=True)
    assert preview['generate_hdr10plus'] is False


def test_write_probe_collision_preserves_foreign_file(tmp_path, monkeypatch):
    from dragontools.core import batch_preflight_storage as storage
    monkeypatch.setattr(storage.uuid, 'uuid4', lambda: SimpleNamespace(hex='collision'))
    existing = tmp_path / '.dragontools_preflight_collision.tmp'
    existing.write_bytes(b'foreign')
    assert storage._can_write_probe(tmp_path)[0] is False
    assert existing.read_bytes() == b'foreign'


def test_move_destination_that_is_a_file_is_a_preflight_error(tmp_path):
    from dragontools.core.batch_preflight_storage import filesystem_preflight
    source = tmp_path / 'source.mkv'
    source.write_bytes(b'video')
    blocked = tmp_path / 'blocked'
    blocked.write_bytes(b'foreign')
    _, warnings, error = filesystem_preflight(str(source), {'target_container': 'mkv',
        'move': {'planned_target': str(blocked)}}, codec='h265', overwrite_original=False)
    assert error is True
    assert any('Ordner' in warning for warning in warnings)


@pytest.mark.parametrize('operation', ['unlink', 'rmtree'])
def test_destructive_helpers_reject_reparse_ancestor(tmp_path, monkeypatch, operation):
    from dragontools.core import path_safety
    parent = tmp_path / 'aliased'
    parent.mkdir()
    target = parent / 'owned'
    if operation == 'unlink':
        target.write_bytes(b'preserve')
    else:
        target.mkdir(); (target / 'file').write_bytes(b'preserve')
    monkeypatch.setattr(path_safety, '_is_link_or_junction', lambda p: p == parent)
    call = path_safety.safe_unlink if operation == 'unlink' else path_safety.safe_rmtree
    assert call(tmp_path, target) is False
    assert target.exists()


@pytest.mark.parametrize('invalid', [True, -1, 1.5, '1.5'])
def test_invalid_track_index_cannot_select_real_track(invalid):
    normalized = normalize_override_dict({'audio_mode': 'custom', 'audio_tracks': [{'index': invalid, 'mode': 'drop'}],
        'subtitle_mode': 'custom', 'subtitle_tracks': [{'index': invalid, 'burn_in': True}]})
    assert normalized['audio_tracks'] == []
    assert normalized['subtitle_tracks'] == []
