"""Renamer identity must survive provider mapping, editing and final commit."""
from pathlib import Path
from types import SimpleNamespace
import pytest

from dragontools.core.movie_renamer import build_series_rename_proposal, build_movie_rename_proposal, parse_movie_release_name, parse_series_release_name, rename_movie_file
from dragontools.core.movie_renamer_candidate_mapping import _series_candidate_from_result
from dragontools.core.movie_renamer_season_override import apply_series_episode_override
from dragontools.core.renamer_candidate_decision import apply_candidate_decision


@pytest.mark.parametrize('shape', ['object', 'dict'])
def test_explicit_provider_specials_cannot_be_rebound_to_source_season(shape):
    parsed = parse_series_release_name('Show.S01E03.mkv')
    raw = (SimpleNamespace(season_number=0, episode_number=3, show_name='Show', title='Special')
        if shape == 'object' else dict(season=0, episode=3, series='Show', episode_title='Special'))
    candidate = _series_candidate_from_result(raw, parsed)
    assert candidate.season == 0
    assert candidate.score < 0.9


def test_alias_does_not_prove_wrong_episode_identity():
    parsed = parse_series_release_name('Alias.S01E03.mkv')
    raw = dict(series='Show', season=2, episode=4, episode_title='Other')
    candidate = _series_candidate_from_result(raw, parsed, title_exception=lambda _: 'Show')
    assert candidate.score < 0.9
    assert candidate.match_reason != 'Aliasregel'


def test_manual_start_episode_shifts_complete_double_episode_identity():
    parsed = parse_series_release_name('Show.S01E03E04.mkv')
    edited, issue = apply_series_episode_override(parsed, 7)
    assert issue is None
    assert edited.episode_numbers == (7, 8)
    calls = []
    def resolver(series, season, episode, year):
        calls.append(episode)
        return [dict(series=series, season=season, episode=episode, episode_title='New title')]
    proposal = build_series_rename_proposal('Show.S01E03E04.mkv', episode_override=7, resolver=resolver)
    assert calls == [7]
    assert 'S01E07E08' in proposal.target_name
    assert 'S01E07E08' in apply_candidate_decision(proposal, 0, proposal.source_path).proposal.target_name


@pytest.mark.parametrize('value', [True, 1.8, float('inf')])
def test_manual_episode_rejects_non_integer_identity(value):
    parsed = parse_series_release_name('Show.S01E03.mkv')
    unchanged, issue = apply_series_episode_override(parsed, value)
    assert issue == 'invalid'
    assert unchanged == parsed


@pytest.mark.parametrize('filename, title, year', [
    ('1917.2019.mkv', '1917', 2019),
    ('2001.A.Space.Odyssey.1968.mkv', '2001 A Space Odyssey', 1968),
    ('Blade.Runner.2049.2017.mkv', 'Blade Runner 2049', 2017),
    ('Spider-Man.2002.mkv', 'Spider-Man', 2002),
    ('Spider-Man.mkv', 'Spider-Man', None),
])
def test_release_parser_preserves_numeric_and_hyphenated_movie_titles(filename, title, year):
    parsed = parse_movie_release_name(filename)
    assert parsed.query_title == title
    assert parsed.year == year


def test_episode_title_year_cannot_become_series_start_year():
    parsed = parse_series_release_name('Show - S01E03 - Sommer 1989.mkv')
    assert parsed.year is None


@pytest.mark.parametrize('kind', ['movie', 'series'])
def test_same_title_remakes_without_source_year_require_review(kind):
    rows = [dict(title='Ranma', series='Ranma', season=1, episode=1, episode_title='Pilot', year=y, id=y) for y in (1989, 2024)]
    proposal = (build_movie_rename_proposal('Ranma.mkv', resolver=lambda *a: rows) if kind == 'movie'
        else build_series_rename_proposal('Ranma.S01E01.mkv', resolver=lambda *a: rows))
    assert len(proposal.candidates) == 2
    assert not proposal.can_auto_accept
    assert not apply_candidate_decision(proposal, 0, proposal.source_path).proposal.can_auto_accept


def test_double_episode_review_cannot_become_auto_accept_on_candidate_reapply():
    proposal = build_series_rename_proposal('Show.S01E03E04.mkv', resolver=lambda *a: [dict(
        series='Show', season=1, episode=3, episode_title='Pilot')])
    assert not proposal.can_auto_accept
    assert not apply_candidate_decision(proposal, 0, proposal.source_path).proposal.can_auto_accept


@pytest.mark.parametrize('phase', ['discovery', 'sidecar_commit'])
def test_rename_source_replaced_during_sidecar_work_remains_untouched(tmp_path, monkeypatch, phase):
    from dragontools.core import movie_renamer_parsing as module
    source = tmp_path / 'Alt.mkv'
    source.write_bytes(b'ORIGINAL')
    sidecar = tmp_path / 'Alt.de.srt'
    sidecar.write_bytes(b'SUBTITLE')
    monkeypatch.setitem(module.SidecarJournal.start.__func__.__globals__, 'app_documents_dir', lambda root=None: tmp_path / 'docs')
    if phase == 'discovery':
        discovery = module.discover_move_companions
        def changed(path):
            found = discovery(path)
            source.write_bytes(b'FOREIGN')
            return found
        monkeypatch.setattr(module, 'discover_move_companions', changed)
    else:
        commit = module.SidecarCommitTransaction.commit
        def changed(transaction):
            result = commit(transaction)
            source.write_bytes(b'FOREIGN')
            return result
        monkeypatch.setattr(module.SidecarCommitTransaction, 'commit', changed)
    with pytest.raises(OSError, match='Quelle|Quelldatei'):
        rename_movie_file(source, 'Neu.mkv')
    assert source.read_bytes() == b'FOREIGN'
    assert sidecar.read_bytes() == b'SUBTITLE'
    assert not (tmp_path / 'Neu.mkv').exists()
    assert not (tmp_path / 'Neu.de.srt').exists()


def test_case_only_rename_works_on_native_windows(tmp_path):
    source = tmp_path / 'Film.mkv'
    source.write_bytes(b'ORIGINAL')
    target = rename_movie_file(source, 'film.mkv')
    assert target.read_bytes() == b'ORIGINAL'
    assert [p.name for p in tmp_path.iterdir()] == ['film.mkv']


@pytest.mark.parametrize('filename', ['Show.S01E03E05.mkv', 'Show.S01E01E02E03E04E05.mkv'])
def test_unrepresentable_multi_episode_identity_cannot_become_safe_single_episode(filename):
    proposal = build_series_rename_proposal(filename, resolver=lambda *a: [dict(
        series='Show', season=1, episode=3 if '03E05' in filename else 1, episode_title='Pilot')])
    assert not proposal.can_auto_accept
    assert not proposal.target_name


@pytest.mark.parametrize('value', [True, 2.5, float('inf')])
def test_explicit_metadata_episode_rejects_non_integer_number(value):
    from dragontools.core.renamer_metadata_browser import MetadataBrowserEpisode
    with pytest.raises(ValueError):
        MetadataBrowserEpisode(1, value, 'Titel')


def test_explicit_mapping_freezes_the_validated_episode_collection():
    from dragontools.core.renamer_metadata_browser import MetadataBrowserHit, MetadataBrowserEpisode, ExplicitSeriesFileMapping
    episodes = [MetadataBrowserEpisode(1, 1, 'Pilot')]
    mapping = ExplicitSeriesFileMapping(Path('raw.mkv'), MetadataBrowserHit('series', 'tmdb', 1, 'Show'), 1, episodes)
    episodes.append(MetadataBrowserEpisode(2, 8, 'FOREIGN'))
    assert len(mapping.episodes) == 1


@pytest.mark.parametrize('filename, force', [('Show.S01E00.mkv', False), ('raw.mkv', True)])
def test_missing_or_invalid_source_episode_returns_a_blocked_proposal(filename, force):
    resolver = lambda *args: []
    proposal = build_series_rename_proposal(filename, resolver=resolver, force=force)
    assert proposal.status in {'needs_episode_mapping', 'needs_season'}
    assert not proposal.target_name and not proposal.can_auto_accept


def test_confirmed_source_year_precedes_wrong_year_alias(monkeypatch):
    from dragontools.core import movie_renamer as module
    monkeypatch.setattr(module, 'apply_title_exception', lambda _: 'Special Ops Lioness')
    proposal = module.build_series_rename_proposal('Lioness.2023.S01E01.mkv', resolver=lambda *a: [
        dict(series='Special Ops Lioness', season=1, episode=1, year=1990, episode_title='Other'),
        dict(series='Lioness', season=1, episode=1, year=2023, episode_title='Pilot')])
    assert proposal.selected.year == 2023
