import csv
from pathlib import Path

import pytest

from dragontools.core.movie_renamer_models import ParsedSeriesReleaseName, SeriesRenameCandidate, SeriesRenameProposal
from dragontools.core.online_metadata_types import OnlineMetadataConfig, OnlineMetadataAuthError
from dragontools.core.renamer_completeness import recognized_series, completeness_targets, compare_season
from dragontools.core import renamer_completeness_provider as provider_module
from dragontools.core.renamer_completeness_export import write_completeness_csv


def proposal(season=1, episode=1, *, provider="thetvdb", identity=11, title="Dragon Ball Z", episodes=()):
    parsed = ParsedSeriesReleaseName("file.mkv", ".mkv", title, season, episode)
    candidate = SeriesRenameCandidate(title, season, episode, provider=provider,
                                     provider_id=identity, episodes=episodes)
    return SeriesRenameProposal(Path("file.mkv"), parsed, (candidate,), candidate, status="ok")


def test_inventory_only_includes_recognized_provider_identities_and_unique_episodes():
    rows = [None, proposal(provider="metadata"), proposal(identity=None), proposal(identity=0),
            proposal(episodes=(1, 2, 3)), proposal(episode=2), proposal(provider="tmdb"),
            proposal(identity=12), proposal(season=0)]
    series = recognized_series(rows)
    assert len(series) == 3
    tvdb = next(item for item in series if item.hit.provider == "thetvdb" and item.hit.provider_id == 11)
    assert tvdb.present == {(0, 1), (1, 1), (1, 2), (1, 3)}
    seasons = completeness_targets((tvdb,))
    assert [target.season for target in seasons] == [0, 1]
    assert "Specials" in seasons[0].label and "TheTVDB" in seasons[0].label
    assert completeness_targets((tvdb,), whole_series=True)[0].season is None


def test_compare_uses_actual_episode_numbers_not_file_counts():
    series = recognized_series([proposal(episode=1), proposal(episode=3), proposal(episode=5)])[0]
    row = compare_season(series, 1, (1, 2, 3))
    assert row.status == "Unvollständig"
    assert row.missing == (2,) and row.extra == (5,)
    assert row.present == (1, 3)


@pytest.fixture
def catalog_service(monkeypatch):
    calls = []

    class Tvdb:
        def __init__(self, _config):
            pass

        def enable_fresh_session(self):
            calls.append("fresh-tvdb")

        def series_episodes(self, identity, **kwargs):
            calls.append(("tvdb", identity, kwargs))
            return [{"seasonNumber": season, "number": number} for season, numbers in
                    [(0, [1, 2]), (1, [1, 2, 3]), (2, [1, 2]), (3, [1, 2, 3, 4, 5])]
                    for number in numbers]

    class Tmdb:
        def __init__(self, _config):
            pass

        def enable_fresh_session(self):
            calls.append("fresh-tmdb")

        def tv_details(self, identity):
            calls.append(("tmdb-details", identity))
            return {"seasons": [{"season_number": 0, "episode_count": 1},
                                {"season_number": 1, "episode_count": 3}]}

        def tv_season_details(self, identity, season, **kwargs):
            calls.append(("tmdb-episodes", identity, season, kwargs))
            return {"episodes": [{"episode_number": number, "season_number": season}
                                 for number in ([1] if season == 0 else [1, 2, 3])]}

    monkeypatch.setattr(provider_module, "TheTvdbClient", Tvdb)
    monkeypatch.setattr(provider_module, "TmdbClient", Tmdb)
    config = OnlineMetadataConfig(tmdb_enabled=True, tmdb_api_key="test", tvdb_enabled=True,
                                  tvdb_bearer_token="test")
    return provider_module.RenamerCompletenessService(config), calls


def test_whole_series_reports_specials_complete_missing_season_and_missing_episodes(catalog_service):
    service, calls = catalog_service
    series = recognized_series([proposal(season=0), proposal(episodes=(1, 2, 3)),
                                proposal(season=3, episode=2, episodes=(2, 3, 4))])[0]
    target = completeness_targets((series,), whole_series=True)[0]
    rows = service.check(target)
    assert [row.status for row in rows] == ["Unvollständig", "Vollständig", "Staffel fehlt", "Unvollständig"]
    assert rows[0].missing == (2,) and rows[2].missing == (1, 2) and rows[3].missing == (1, 5)
    assert calls[0] == "fresh-tvdb"
    assert calls[1][2]["force_refresh"] is True
    service.check(target)
    assert sum(isinstance(call, tuple) and call[0] == "tvdb" for call in calls) == 1


def test_season_check_uses_selected_source_without_fallback(catalog_service):
    service, calls = catalog_service
    series = recognized_series([proposal(provider="tmdb", episodes=(1, 2, 3))])[0]
    rows = service.check(completeness_targets((series,))[0])
    assert len(rows) == 1 and rows[0].season == 1 and rows[0].status == "Vollständig"
    assert "fresh-tmdb" in calls and "fresh-tvdb" not in calls
    assert next(call for call in calls if isinstance(call, tuple) and call[0] == "tmdb-episodes")[3]["force_refresh"]


def test_unlisted_local_season_is_not_claimed_complete(catalog_service):
    service, _calls = catalog_service
    series = recognized_series([proposal(season=9)])[0]
    row = service.check(completeness_targets((series,))[0])[0]
    assert row.status == "Nicht prüfbar" and "nicht geführt" in row.note


def test_provider_error_is_not_complete(catalog_service, monkeypatch):
    service, _calls = catalog_service
    series = recognized_series([proposal(provider="tmdb")])[0]
    client = service._client("tmdb")
    monkeypatch.setattr(client, "tv_season_details", lambda *_args, **_kwargs: {"episodes": []})
    row = service.check(completeness_targets((series,))[0])[0]
    assert row.status == "Nicht prüfbar" and "nicht überein" in row.note


def test_missing_provider_credentials_do_not_use_another_provider():
    config = OnlineMetadataConfig(tmdb_enabled=True, tmdb_api_key="test")
    series = recognized_series([proposal()])[0]
    with pytest.raises(OnlineMetadataAuthError, match="TheTVDB"):
        provider_module.RenamerCompletenessService(config).check(completeness_targets((series,))[0])


def test_cancellation_stops_before_any_provider_query(catalog_service):
    service, calls = catalog_service
    series = recognized_series([proposal()])[0]
    with pytest.raises(provider_module.CompletenessCancelled):
        service.check(completeness_targets((series,))[0], cancelled=lambda: True)
    assert not calls


def test_empty_catalog_does_not_prove_completeness():
    series = recognized_series([proposal()])[0]
    assert compare_season(series, 1, ()).status == "Nicht prüfbar"


def test_csv_matches_report_and_preserves_unicode_and_safe_spreadsheet_cells(tmp_path):
    series = recognized_series([proposal(title="=危険", season=0)])[0]
    row = compare_season(series, 0, (1, 2, 3))
    path = tmp_path / "report.csv"
    write_completeness_csv((row,), path)
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        header, cells = list(csv.reader(handle, delimiter=";"))
    assert cells[0] == "'=危険" and cells[3] == "Specials (Staffel 0)"
    assert cells[7] == "2, 3" and "Fehlende Folgen" in header


def test_real_tmdb_transport_fetches_details_and_episode_list(monkeypatch, tmp_path):
    from dragontools.core.online_metadata_tmdb import TmdbClient
    from urllib.parse import urlsplit

    calls = []
    def http_get(url, _headers, _timeout):
        path = urlsplit(url).path
        calls.append(path)
        if path.endswith("/tv/11"):
            return {"id": 11, "seasons": [{"season_number": 1, "episode_count": 2}]}
        if path.endswith("/tv/11/season/1"):
            return {"id": 101, "season_number": 1,
                    "episodes": [{"id": 501, "season_number": 1, "episode_number": 1},
                                 {"id": 502, "season_number": 1, "episode_number": 2}]}
        raise AssertionError(path)

    monkeypatch.setattr(provider_module, "TmdbClient", lambda config: TmdbClient(
        config, cache_dir=tmp_path, http_get=http_get))
    config = OnlineMetadataConfig(tmdb_enabled=True, tmdb_api_key="test", cache_enabled=False)
    series = recognized_series([proposal(provider="tmdb")])[0]
    result = provider_module.RenamerCompletenessService(config).check(completeness_targets((series,))[0])
    assert result[0].missing == (2,)
    assert calls == ["/3/tv/11", "/3/tv/11/season/1"]
