from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import json
import time

import pytest

from dragontools.core.online_metadata import OnlineMetadataConfig, TheTvdbClient, TmdbClient
from dragontools.core.online_metadata_types import OnlineMetadataError, OnlineMetadataResponseError


def config(**changes):
    return replace(OnlineMetadataConfig(tmdb_enabled=True, tmdb_read_token='test-token',
        tvdb_enabled=True, tvdb_bearer_token='test-bearer', cache_enabled=False), **changes)


@pytest.mark.parametrize('provider', ['tmdb', 'thetvdb'])
def test_direct_episode_retains_verified_series_year(tmp_path, provider):
    def get(url, *_args):
        path = urlparse(url).path
        if '/search' in path:
            return {'results': [{'id': 1, 'name': 'Show', 'first_air_date': '2024-01-01'}]} if provider == 'tmdb' else {'data': [{'id': 1, 'name': 'Show', 'year': '2024'}]}
        if '/episodes/' in path:
            return {'data': {'episodes': [{'id': 2, 'seasonNumber': 1, 'number': 1, 'name': 'Pilot'}]}}
        if '/episode/' in path:
            return {'id': 2, 'season_number': 1, 'episode_number': 1, 'name': 'Pilot'}
        return {'id': 1, 'name': 'Show', 'first_air_date': '2024-01-01'} if provider == 'tmdb' else {'data': {'id': 1, 'name': 'Show', 'firstAired': '2024-01-01'}}
    client = (TmdbClient if provider == 'tmdb' else TheTvdbClient)(config(), cache_dir=tmp_path, http_get=get)
    result = client.resolve_episode_file('Show (2024) - S01E01.mkv')
    assert result is not None and result.first_air_year == 2024


def test_tvdb_later_page_is_loaded_and_reused_as_complete_batch(tmp_path):
    calls = []
    def get(url, *_args):
        page = int(parse_qs(urlparse(url).query).get('page', ['0'])[0])
        calls.append(page)
        record = {'id': page + 10, 'seasonNumber': 1, 'number': page + 1, 'name': f'Part {page + 1}'}
        return {'data': {'episodes': [record]}, 'links': {'next': '?page=1' if page == 0 else None}}
    client = TheTvdbClient(config(), cache_dir=tmp_path, http_get=get)
    result = client.resolve_episode_record(1, 1, 2)
    assert result is not None and result['id'] == 11
    assert len(client.series_episodes(1)) == 2
    assert calls == [0, 1]


@pytest.mark.parametrize('next_link', ['?page=0', '?page=bad', 'https://foreign.invalid/v4/series/1/episodes/default/deu?page=1'])
def test_tvdb_broken_pagination_cannot_become_complete_cached_list(tmp_path, next_link):
    calls = []
    def get(url, *_args):
        calls.append(url)
        return {'data': {'episodes': [{'id': 10, 'seasonNumber': 1, 'number': 1, 'name': 'Pilot'}]}, 'links': {'next': next_link}}
    client = TheTvdbClient(config(), cache_dir=tmp_path, http_get=get)
    with pytest.raises(OnlineMetadataResponseError):
        client.series_episodes(1)
    assert client._episode_batch_cache == {}
    assert len(calls) == 1


def test_tvdb_second_page_failure_does_not_cache_partial_or_switch_language(tmp_path):
    calls = []
    def get(url, *_args):
        calls.append(url)
        if 'page=1' in url:
            raise OnlineMetadataError('second page unavailable')
        return {'data': {'episodes': [{'id': 10, 'seasonNumber': 1, 'number': 1, 'name': 'Pilot'}]}, 'links': {'next': '?page=1'}}
    client = TheTvdbClient(config(), cache_dir=tmp_path, http_get=get)
    with pytest.raises(OnlineMetadataError, match='second page'):
        client.series_episodes(1)
    assert client._episode_batch_cache == {}
    assert len(calls) == 2


@pytest.mark.parametrize('payload', [[], {'created': float('nan'), 'data': {'id': 1}}, {'created': time.time() + 86400, 'data': {'id': 1}}])
def test_invalid_cache_envelope_is_a_miss(tmp_path, payload):
    from dragontools.core.online_metadata_cache import read_metadata_cache
    (tmp_path / 'key.json').write_text(json.dumps(payload), encoding='utf-8')
    assert read_metadata_cache(tmp_path, 'key', enabled=True, cache_days=7) is None


def test_failed_cache_publish_keeps_previous_complete_file(tmp_path, monkeypatch):
    import dragontools.core.online_metadata_cache as module
    module.write_metadata_cache(tmp_path, 'key', {'id': 1}, enabled=True)
    previous = (tmp_path / 'key.json').read_bytes()
    import os
    monkeypatch.setattr(os, 'replace', lambda *_a, **_k: (_ for _ in ()).throw(OSError('locked')))
    module.write_metadata_cache(tmp_path, 'key', {'id': 2}, enabled=True)
    assert (tmp_path / 'key.json').read_bytes() == previous
    assert list(tmp_path.iterdir()) == [tmp_path / 'key.json']


@pytest.mark.parametrize('provider', ['tmdb', 'thetvdb'])
def test_request_cache_isolated_from_nested_caller_mutation(tmp_path, provider):
    original = {'results': [{'id': 1, 'title': 'Correct'}]} if provider == 'tmdb' else {'data': [{'id': 1, 'name': 'Correct'}]}
    client = (TmdbClient if provider == 'tmdb' else TheTvdbClient)(config(), cache_dir=tmp_path, http_get=lambda *_a: original)
    endpoint = '/search/movie' if provider == 'tmdb' else '/search'
    first = client._request_json(endpoint, {})
    key, field = ('results', 'title') if provider == 'tmdb' else ('data', 'name')
    first[key][0][field] = 'Changed by caller'
    original[key][0][field] = 'Changed by adapter'
    assert client._request_json(endpoint, {})[key][0][field] == 'Correct'


@pytest.mark.parametrize('provider', ['tmdb', 'thetvdb'])
def test_starting_fresh_session_invalidates_higher_batch_caches(tmp_path, provider):
    client = (TmdbClient if provider == 'tmdb' else TheTvdbClient)(config(), cache_dir=tmp_path)
    client._renamer_search_cache[('old',)] = [{'id': 1}]
    if provider == 'tmdb':
        client._renamer_season_cache[(1, 1, 'de-DE')] = {'id': 3}
    else:
        client._episode_batch_cache[(1, 'default', 'deu')] = [{'id': 3}]
        client._episode_batch_fresh.add((1, 'default', 'deu'))
        client._series_details_batch_cache[(1, True)] = {'data': {'id': 1}}
        client._series_details_batch_fresh.add((1, True))
    client.enable_fresh_session()
    assert not client._renamer_search_cache
    for name in ['_renamer_season_cache', '_episode_batch_cache', '_episode_batch_fresh', '_series_details_batch_cache', '_series_details_batch_fresh']:
        assert not getattr(client, name, ())


def test_provider_is_part_of_shared_persistent_cache_identity(tmp_path):
    tmdb = TmdbClient(config(), cache_dir=tmp_path)
    tvdb = TheTvdbClient(config(), cache_dir=tmp_path)
    assert tmdb._cache_key('/same', {'language': 'deu'}) != tvdb._cache_key('/same', {'language': 'deu'})


@pytest.mark.parametrize('payload', [{'data': []}, {'data': {'token': 123}}, {'data': {'token': 'bad\nheader'}}])
def test_malformed_login_is_classified_without_saving_token(tmp_path, payload):
    from dragontools.core.online_metadata import OnlineMetadataAuthError
    saved = []
    client = TheTvdbClient(config(tvdb_bearer_token='', tvdb_api_key='test-key', tvdb_bearer_token_store=saved.append), cache_dir=tmp_path, http_post=lambda *_a: payload)
    with pytest.raises(OnlineMetadataAuthError):
        client._auth_token()
    assert saved == [] and client._token == ''


@pytest.mark.parametrize('path', ['direct', 'candidates', 'renamer'])
def test_tmdb_wrong_episode_identity_cannot_be_labelled_as_requested_episode(tmp_path, path):
    def get(url, *_args):
        if '/search' in url:
            return {'results': [{'id': 1, 'name': 'Show', 'first_air_date': '2024-01-01'}]}
        if '/episode/' in url:
            return {'id': 2, 'season_number': 1, 'episode_number': 2, 'name': 'Wrong episode'}
        if '/season/' in url:
            return {'id': 3, 'season_number': 2, 'episodes': [{'id': 2, 'season_number': 2, 'episode_number': 1, 'name': 'Wrong season'}]}
        return {'id': 1, 'name': 'Show', 'first_air_date': '2024-01-01'}
    client = TmdbClient(config(), cache_dir=tmp_path, http_get=get)
    operation = {'direct': client.resolve_episode_file, 'candidates': client.resolve_episode_candidates, 'renamer': client.resolve_renamer_episode_candidates}[path]
    with pytest.raises(OnlineMetadataResponseError):
        operation('Show (2024) - S01E01.mkv')


def test_tvdb_prefixed_search_identifier_reaches_candidate_and_detail(tmp_path):
    client = TheTvdbClient(config(), cache_dir=tmp_path,
        http_get=lambda url, *_a: {'data': [{'id': 'series-123', 'name': 'Show', 'year': '2024'}]} if '/search' in url else {'data': {'id': 123, 'name': 'Show', 'firstAired': '2024-01-01'}})
    result = client.resolve_series('Show', year=2024)
    assert result is not None and result.provider_id == 123


@pytest.mark.parametrize('field', ['seasonNumber', 'number'])
def test_tvdb_fractional_episode_fields_cannot_match_requested_integer(tmp_path, field):
    record = {'id': 10, 'seasonNumber': 1, 'number': 1, 'name': 'Wrong identity'}
    record[field] = 1.5
    client = TheTvdbClient(config(), cache_dir=tmp_path,
        http_get=lambda *_a: {'data': {'episodes': [record]}})
    assert client.resolve_episode_record(1, 1, 1) is None


def test_unmodified_dialog_token_does_not_replace_concurrent_refresh(tmp_path):
    from PyQt6.QtCore import QSettings
    from dragontools.core.secret_settings import read_secret, write_secret
    from dragontools.core.settings_metadata import SET_KEY_METADATA_TVDB_BEARER_TOKEN
    from dragontools.gui.online_metadata_settings_state import load_online_metadata_settings, save_online_metadata_settings
    settings = QSettings(str(tmp_path / 'profile.ini'), QSettings.Format.IniFormat)
    write_secret(settings, SET_KEY_METADATA_TVDB_BEARER_TOKEN, 'old')
    loaded = load_online_metadata_settings(settings)
    write_secret(settings, SET_KEY_METADATA_TVDB_BEARER_TOKEN, 'fresh')
    save_online_metadata_settings(settings, replace(loaded, language='fr-FR'))
    assert read_secret(settings, SET_KEY_METADATA_TVDB_BEARER_TOKEN) == 'fresh'


def test_refresh_accessors_keep_native_settings_file_and_group(tmp_path, monkeypatch):
    from PyQt6.QtCore import QSettings
    from dragontools.core import online_metadata_config as module
    from dragontools.core.secret_settings import read_secret, write_secret
    from dragontools.core.settings_metadata import SET_KEY_METADATA_TVDB_BEARER_TOKEN
    settings = QSettings(str(tmp_path / 'profile.ini'), QSettings.Format.IniFormat)
    settings.beginGroup('profile-a')
    write_secret(settings, SET_KEY_METADATA_TVDB_BEARER_TOKEN, 'old')
    settings.sync()
    monkeypatch.setattr(module, 'app_qsettings', lambda: None)
    cfg = module.config_from_settings(settings)
    cfg.tvdb_bearer_token_store('fresh')
    settings.sync()
    assert read_secret(settings, SET_KEY_METADATA_TVDB_BEARER_TOKEN) == 'fresh'
    assert cfg.tvdb_bearer_token_load() == 'fresh'
    settings.endGroup()
    assert not settings.contains(SET_KEY_METADATA_TVDB_BEARER_TOKEN)


@pytest.mark.parametrize('bad_id', [True, 1.5, float('inf'), 0, -1])
def test_tmdb_malformed_identifier_is_skipped_without_losing_valid_candidate(tmp_path, bad_id):
    client = TmdbClient(config(), cache_dir=tmp_path, http_get=lambda *_a: {'results': [
        {'id': bad_id, 'title': 'Bad'}, {'id': 7, 'title': 'Correct'}]})
    assert [item['provider_id'] for item in client.search_movies('Correct')] == [7]


def test_tvdb_default_language_is_in_persistent_search_identity(tmp_path):
    calls = []
    def get(url, *_args):
        language = parse_qs(urlparse(url).query).get('language', ['missing'])[0]
        calls.append(language)
        return {'data': [{'id': 1, 'name': language}]}
    first = TheTvdbClient(config(cache_enabled=True, language='de-DE'), cache_dir=tmp_path, http_get=get)
    second = TheTvdbClient(config(cache_enabled=True, language='fr-FR'), cache_dir=tmp_path, http_get=get)
    assert first.search_series('Show')[0]['name'] == 'deu'
    assert second.search_series('Show')[0]['name'] == 'fra'
    assert calls == ['deu', 'fra']


def test_incomplete_http_body_uses_bounded_transient_retry(monkeypatch):
    from http.client import IncompleteRead
    from urllib.request import Request
    from dragontools.core import online_metadata_http as module
    from dragontools.core.online_metadata_retry import RetryableOnlineMetadataError
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_a): return False
        def read(self): raise IncompleteRead(b'{', 10)
    monkeypatch.setattr(module, 'urlopen', lambda *_a, **_k: Response())
    with pytest.raises(RetryableOnlineMetadataError):
        module.request_json(Request('https://example.invalid'), 1, label='TMDB')


def test_manually_changed_bearer_still_replaces_concurrent_token(tmp_path):
    from PyQt6.QtCore import QSettings
    from dragontools.core.secret_settings import read_secret, write_secret
    from dragontools.core.settings_metadata import SET_KEY_METADATA_TVDB_BEARER_TOKEN
    from dragontools.gui.online_metadata_settings_state import load_online_metadata_settings, save_online_metadata_settings
    settings = QSettings(str(tmp_path / 'profile.ini'), QSettings.Format.IniFormat)
    write_secret(settings, SET_KEY_METADATA_TVDB_BEARER_TOKEN, 'old')
    loaded = load_online_metadata_settings(settings)
    write_secret(settings, SET_KEY_METADATA_TVDB_BEARER_TOKEN, 'fresh')
    save_online_metadata_settings(settings, replace(loaded, tvdb_bearer_token='manual'))
    assert read_secret(settings, SET_KEY_METADATA_TVDB_BEARER_TOKEN) == 'manual'


@pytest.mark.parametrize('provider', ['tmdb', 'thetvdb'])
def test_language_year_and_provider_search_cache_dimensions(tmp_path, provider):
    client = (TmdbClient if provider == 'tmdb' else TheTvdbClient)(config(), cache_dir=tmp_path)
    assert len({client._cache_key('/search', params) for params in [
        {'query': 'Show', 'year': '2024', 'language': 'de'},
        {'query': 'Show', 'year': '1989', 'language': 'de'},
        {'query': 'Show', 'year': '2024', 'language': 'en'}]}) == 3


@pytest.mark.parametrize('provider', ['tmdb', 'thetvdb'])
def test_clear_cache_invalidates_active_session_results(tmp_path, provider):
    title = ['Old']
    def get(*_a):
        return {'results': [{'id': 1, 'title': title[0]}]} if provider == 'tmdb' else {'data': [{'id': 1, 'name': title[0]}]}
    client = (TmdbClient if provider == 'tmdb' else TheTvdbClient)(config(cache_enabled=True), cache_dir=tmp_path, http_get=get)
    assert client.search_movies('Show')
    title[0] = 'New'
    assert client.clear_cache() == 1
    result = client.search_movies('Show')[0]
    assert result.get('title', result.get('name')) == 'New'


def test_tmdb_season_endpoint_rejects_wrong_season_before_browser_can_use_it(tmp_path):
    client = TmdbClient(config(), cache_dir=tmp_path, http_get=lambda *_a: {'id': 1, 'season_number': 2, 'episodes': []})
    with pytest.raises(OnlineMetadataResponseError):
        client.tv_season_details(1, 1)


@pytest.mark.parametrize('field', ['seasonNumber', 'number'])
def test_metadata_browser_uses_same_integer_episode_identity_as_provider(field):
    from dragontools.core.renamer_metadata_browser import RenamerMetadataBrowserService
    record = {'seasonNumber': 1, 'number': 1}
    record[field] = 1.5
    operation = RenamerMetadataBrowserService._tvdb_season_number if field == 'seasonNumber' else RenamerMetadataBrowserService._tvdb_episode_number
    assert operation(record) is None
from types import SimpleNamespace
import pytest


def test_preflight_callback_internal_year_error_cannot_trigger_unfiltered_retry():
    from dragontools.gui.preflight_metadata_common import MetadataLookupCache
    from dragontools.gui.preflight_metadata_series_sources import SeriesOnlineLookup
    calls = []
    def lookup(_name, _settings, *, year=None):
        calls.append(year)
        if year is not None:
            raise TypeError('year decoding failed')
        return SimpleNamespace(first_air_year=1989)
    source = SeriesOnlineLookup(object(), 'Show', MetadataLookupCache(), lookup)
    with pytest.raises(TypeError, match='year decoding failed'):
        source.lookup(2024)
    assert calls == [2024] and source.cache.online_series == {}


def test_preflight_legacy_callback_cannot_override_authoritative_year():
    from dragontools.gui.preflight_metadata_common import MetadataLookupCache
    from dragontools.gui.preflight_metadata_series_sources import SeriesOnlineLookup
    source = SeriesOnlineLookup(object(), 'Show', MetadataLookupCache(),
        lambda _name, _settings: SimpleNamespace(first_air_year=1989))
    assert source.lookup(2024) is None


def test_preflight_legacy_callback_can_return_matching_authoritative_year():
    from dragontools.gui.preflight_metadata_common import MetadataLookupCache
    from dragontools.gui.preflight_metadata_series_sources import SeriesOnlineLookup
    result = SimpleNamespace(first_air_year=2024)
    calls = []
    def lookup(_name, _settings):
        calls.append(True)
        return result
    source = SeriesOnlineLookup(object(), 'Show', MetadataLookupCache(), lookup)
    assert source.lookup(2024) is result
    assert source.lookup(2024) is result and len(calls) == 1

