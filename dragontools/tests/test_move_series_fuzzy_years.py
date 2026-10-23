from __future__ import annotations

from pathlib import Path

import pytest

from dragontools.core.move_routing import MoveRouter
from dragontools.rules.move_rules import find_series_dir_candidates, parse_series_match_details


def router_for(base, ask):
    return MoveRouter(
        tv_path='', anime_path=str(base), filme_path='', all_video_files=[],
        planned_target_for=lambda _path: None, ask=ask, log=lambda *_args: None,
    )


def no_question(_payload):
    pytest.fail('A known unique edition must not require another choice')


@pytest.mark.parametrize('filename, year', [
    ('Ranma ½ (2024) - S01E01.mkv', 2024),
    ('Ranma.1-2.2024.S01E01.German.1080p.mkv', 2024),
    ('Ranma ½ 2024 - S01E01.mkv', 2024),
    ('Ranma ½ (1989) – S01E01.mkv', 1989),
    ('Ranma ½ - S01E01 - Episode (2024).mkv', None),
    ('Kaiju No. 8 - S01E01.mkv', None),
])
def test_series_parser_keeps_only_title_year(filename, year):
    parsed = parse_series_match_details(filename)
    assert parsed is not None
    assert parsed['year'] == year


@pytest.mark.parametrize('title', [
    'Girl Raising Projekt Restart',
    'Girl_Raising_Projekt_Restart',
    'Girl.Raising.Projekt.Restart',
    'MAGICAL GIRL RAISING PROJECT RESTART',
])
def test_real_filename_routes_to_existing_fuzzy_series(tmp_path, title):
    existing = tmp_path / 'MAGICAL GIRL RAISING PROJECT restart (2026)'
    existing.mkdir()
    router = router_for(tmp_path, no_question)
    assert router.route(str(tmp_path / f'{title} - S01E02.mkv')) == str(existing / 'Staffel 01')


@pytest.mark.parametrize('filename', [
    'Ranma ½ (2024) - S01E01.mkv',
    'Ranma.1-2.2024.S01E01.German.1080p.mkv',
])
def test_runtime_move_never_uses_older_edition_for_known_filename_year(tmp_path, filename):
    old = tmp_path / 'Ranma ½ (1989)'
    new = tmp_path / 'Ranma ½ (2024)'
    old.mkdir()
    new.mkdir()
    router = router_for(tmp_path, no_question)
    assert router.route(str(tmp_path / filename)) == str(new / 'Staffel 01')
    assert not (old / 'Staffel 01').exists()


def test_missing_known_edition_creates_year_folder_instead_of_using_old_one(tmp_path):
    old = tmp_path / 'Ranma ½ (1989)'
    old.mkdir()
    router = router_for(tmp_path, no_question)
    expected = tmp_path / 'Ranma ½ (2024)' / 'Staffel 01'
    assert router.route(str(tmp_path / 'Ranma ½ (2024) - S01E01.mkv')) == str(expected)
    assert expected.is_dir()
    assert not (old / 'Staffel 01').exists()


def test_runtime_move_without_year_offers_both_ranma_editions(tmp_path):
    old, new = tmp_path / 'Ranma ½ (1989)', tmp_path / 'Ranma ½ (2024)'
    old.mkdir()
    new.mkdir()
    requests = []

    def ask(payload):
        requests.append(payload)
        assert payload['type'] == 'choose_series_folder'
        assert [item['path'] for item in payload['candidates']] == [str(old), str(new)]
        return {'path': str(new)}

    assert router_for(tmp_path, ask).route(str(tmp_path / 'Ranma ½ - S01E01.mkv')) == str(new / 'Staffel 01')
    assert len(requests) == 1
    assert not (old / 'Staffel 01').exists()


def test_cancelled_fuzzy_folder_choice_creates_no_season_folder(tmp_path):
    old = tmp_path / 'MAGICAL GIRL RAISING PROJECT Restart (2016)'
    new = tmp_path / 'Girl Raising Projekt Restart (2026)'
    old.mkdir()
    new.mkdir()
    assert router_for(tmp_path, lambda _payload: {'abort': True}).route(
        str(tmp_path / 'MAGICAL GIRL RAISING PROJECT RESTART - S01E01.mkv')
    ) == ''
    assert not (old / 'Staffel 01').exists()
    assert not (new / 'Staffel 01').exists()


@pytest.mark.parametrize('title', [
    'MAGICAL GIRL RAISING PROJECT',
    'MAGICAL GIRL PROJECT Restart',
    'Raising Project Restart',
    'Girl Raising Projekte Restart',
    'MAGICAL GIRL RAISING PROJECT Reboot',
])
def test_fuzzy_matching_keeps_distinguishing_words(tmp_path, title):
    (tmp_path / 'MAGICAL GIRL RAISING PROJECT Restart (2026)').mkdir()
    assert find_series_dir_candidates(str(tmp_path), title) == []


def test_short_substring_is_not_a_series_match(tmp_path):
    (tmp_path / 'xxxxxxxdungen mao (2015)').mkdir()
    assert find_series_dir_candidates(str(tmp_path), 'mao') == []


def test_exact_and_fuzzy_matches_same_year_still_require_choice(tmp_path):
    exact = tmp_path / 'MAGICAL GIRL RAISING PROJECT Restart (2026)'
    fuzzy = tmp_path / 'Girl Raising Projekt Restart (2026)'
    wrong_year = tmp_path / 'MAGICAL GIRL RAISING PROJECT Restart (2016)'
    for folder in (exact, fuzzy, wrong_year):
        folder.mkdir()
    assert find_series_dir_candidates(str(tmp_path), 'MAGICAL GIRL RAISING PROJECT RESTART', year=2026) == [
        str(exact), str(fuzzy),
    ]


def test_fuzzy_file_is_not_a_folder_candidate(tmp_path):
    (tmp_path / 'MAGICAL GIRL RAISING PROJECT Restart (2026)').write_text('file')
    assert find_series_dir_candidates(str(tmp_path), 'Girl Raising Projekt Restart') == []


@pytest.mark.parametrize('database_hit', [False, True])
def test_preflight_keeps_fuzzy_editions_when_online_suggests_year(tmp_path, database_hit):
    from dragontools.gui.preflight_metadata_common import MetadataLookupCache
    from dragontools.gui.preflight_metadata_series import resolve_series_metadata
    from dragontools.core.online_metadata_types import SeriesMetadataSuggestion

    old = tmp_path / 'MAGICAL GIRL RAISING PROJECT Restart (2016)'
    new = tmp_path / 'Girl Raising Projekt Restart (2026)'
    old.mkdir()
    new.mkdir()
    name = 'MAGICAL GIRL RAISING PROJECT RESTART'
    result = resolve_series_metadata(
        {'series_name': name, 'base': str(tmp_path)},
        settings=None, online_enabled=True, cache=MetadataLookupCache(),
        find_series_dir_from_settings=lambda *_a, **_kw: {'series_dir': str(old)} if database_hit else None,
        find_series_dir_candidates=find_series_dir_candidates,
        suggest_series_metadata_for_name=lambda *_a, **_kw: SeriesMetadataSuggestion(name, 2026),
    )
    assert [item['path'] for item in result['__series_dir_choices__']] == [str(old), str(new)]


def test_preflight_known_year_uses_fuzzy_edition(tmp_path):
    from dragontools.gui.preflight_metadata_common import MetadataLookupCache
    from dragontools.gui.preflight_metadata_series import resolve_series_metadata

    old = tmp_path / 'MAGICAL GIRL RAISING PROJECT Restart (2016)'
    new = tmp_path / 'Girl Raising Projekt Restart (2026)'
    old.mkdir()
    new.mkdir()
    result = resolve_series_metadata(
        {'series_name': 'MAGICAL GIRL RAISING PROJECT RESTART', 'year': 2026, 'base': str(tmp_path)},
        settings=None, online_enabled=True, cache=MetadataLookupCache(),
        find_series_dir_from_settings=lambda *_a, **_kw: None,
        find_series_dir_candidates=find_series_dir_candidates,
        suggest_series_metadata_for_name=no_question,
    )
    assert result['__existing_series_dir__'] == str(new)


def test_preflight_dropdown_requires_and_preserves_explicit_choice(qapp, tmp_path):
    from dragontools.gui.preflight_series_widget import SeriesGroupWidget

    old = tmp_path / 'MAGICAL GIRL RAISING PROJECT Restart (2016)'
    new = tmp_path / 'Girl Raising Projekt Restart (2026)'
    old.mkdir()
    new.mkdir()
    name = 'MAGICAL GIRL RAISING PROJECT RESTART'
    source = str(tmp_path / f'{name} - S01E01.mkv')
    widget = SeriesGroupWidget(name, [{'path': source, 'season': 1}], str(tmp_path), None)
    try:
        widget.apply_existing_series_dir_choices(
            series_name=name,
            choices=[{'path': str(folder), 'base': str(tmp_path), 'base_type': 'Anime'} for folder in (old, new)],
        )
        assert not widget._folder_choice_combo.isHidden()
        assert widget.validate()[0] is False
        widget._folder_choice_combo.setCurrentIndex(2)
        assert widget.validate()[0] is True
        assert Path(widget.get_planned_targets()[source]) == new / 'Staffel 01'
    finally:
        widget.close()
