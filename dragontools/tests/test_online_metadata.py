from __future__ import annotations

import pytest
from urllib.parse import parse_qs, urlparse


def test_parse_movie_query_extracts_title_and_year_from_release_name():
    from dragontools.core.online_metadata import parse_movie_query

    parsed = parse_movie_query("Toy.Story.3.2010.German.DL.1080p.WEB.H264.mkv")

    assert parsed.title == "Toy Story 3"
    assert parsed.year == 2010


def test_parse_movie_query_keeps_manual_dotted_title_without_video_extension():
    from dragontools.core.online_metadata import parse_movie_query

    parsed = parse_movie_query("Ready.or.Not.2019")

    assert parsed.title == "Ready or Not"
    assert parsed.year == 2019


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Alarmstufe Rot Filmreihe", "Alarmstufe Rot"),
        ("Toy Story Collection", "Toy Story"),
        ("Sissi Sammlung", "Sissi"),
        ("Matrix - Kollektion", "Matrix"),
    ],
)
def test_clean_tmdb_collection_name_removes_provider_suffixes(raw, expected):
    from dragontools.core.online_metadata import clean_tmdb_collection_name

    assert clean_tmdb_collection_name(raw) == expected


def test_tmdb_client_resolves_collection_with_read_token(tmp_path):
    from dragontools.core.online_metadata import OnlineMetadataConfig, TmdbClient

    calls: list[str] = []

    def fake_get(url: str, headers: dict[str, str], timeout: int):
        calls.append(url)
        assert headers["Authorization"] == "Bearer token"
        if "/search/movie" in url:
            return {
                "results": [
                    {
                        "id": 11,
                        "title": "Test Film",
                        "release_date": "2019-01-01",
                    }
                ]
            }
        if "/movie/11" in url:
            return {
                "id": 11,
                "title": "Test Film",
                "original_title": "Original Test Film",
                "release_date": "2019-01-01",
                "belongs_to_collection": {"id": 99, "name": "Alter Name"},
            }
        if "/collection/99" in url:
            return {"id": 99, "name": "Test Filmreihe", "parts": [{}, {}]}
        raise AssertionError(url)

    client = TmdbClient(
        OnlineMetadataConfig(tmdb_enabled=True, tmdb_read_token="token", cache_enabled=False),
        cache_dir=tmp_path,
        http_get=fake_get,
    )

    suggestion = client.resolve_movie("Test Film", year=2019)

    assert suggestion is not None
    assert suggestion.movie_folder_name == "Test Film (2019)"
    assert suggestion.collection_name == "Test"
    assert suggestion.collection_part_count == 2
    assert len(calls) == 3


def test_tmdb_client_retries_movie_search_with_german_umlaut_variant(tmp_path):
    from dragontools.core.online_metadata import OnlineMetadataConfig, TmdbClient

    queries: list[str] = []

    def fake_get(url: str, headers: dict[str, str], timeout: int):
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        if parsed.path.endswith("/search/movie"):
            query = params.get("query", [""])[0]
            queries.append(query)
            if query == "Der Kinderflüsterer":
                return {
                    "results": [
                        {
                            "id": 55,
                            "title": "Der Kinderflüsterer",
                            "release_date": "2026-02-01",
                        }
                    ]
                }
            return {"results": []}
        if parsed.path.endswith("/movie/55"):
            return {
                "id": 55,
                "title": "Der Kinderflüsterer",
                "original_title": "Der Kinderflüsterer",
                "release_date": "2026-02-01",
            }
        raise AssertionError(url)

    client = TmdbClient(
        OnlineMetadataConfig(
            tmdb_enabled=True,
            tmdb_read_token="token",
            fallback_language="de-DE",
            cache_enabled=False,
        ),
        cache_dir=tmp_path,
        http_get=fake_get,
    )

    suggestion = client.resolve_movie("Der Kinderfluesterer", year=2026)

    assert suggestion is not None
    assert suggestion.movie_folder_name == "Der Kinderflüsterer (2026)"
    assert queries == ["Der Kinderfluesterer", "Der Kinderflüsterer"]


def test_tmdb_client_resolves_series_year_with_read_token(tmp_path):
    from dragontools.core.online_metadata import OnlineMetadataConfig, TmdbClient

    calls: list[str] = []

    def fake_get(url: str, headers: dict[str, str], timeout: int):
        calls.append(url)
        assert headers["Authorization"] == "Bearer token"
        if "/search/tv" in url:
            return {
                "results": [
                    {
                        "id": 42,
                        "name": "Test Serie",
                        "first_air_date": "2024-04-10",
                    }
                ]
            }
        if "/tv/42" in url:
            return {
                "id": 42,
                "name": "Test Serie",
                "original_name": "Original Test Serie",
                "first_air_date": "2024-04-10",
            }
        raise AssertionError(url)

    client = TmdbClient(
        OnlineMetadataConfig(tmdb_enabled=True, tmdb_read_token="token", cache_enabled=False),
        cache_dir=tmp_path,
        http_get=fake_get,
    )

    suggestion = client.resolve_series("Test Serie")

    assert suggestion is not None
    assert suggestion.folder_name == "Test Serie (2024)"
    assert suggestion.original_name == "Original Test Serie"
    assert len(calls) == 2


def test_series_folder_name_removes_brand_colon_without_underscore():
    from dragontools.core.online_metadata import SeriesMetadataSuggestion

    suggestion = SeriesMetadataSuggestion(
        query_title="ReZero - Starting Life in Another World",
        query_year=None,
        tmdb_id=42,
        name="Re:ZERO - Starting Life in Another World",
        original_name="Re:ZERO - Starting Life in Another World",
        first_air_year=2016,
    )

    assert suggestion.folder_name == "ReZERO - Starting Life in Another World (2016)"


def test_series_folder_name_replaces_title_colon_with_separator():
    from dragontools.core.online_metadata import SeriesMetadataSuggestion

    suggestion = SeriesMetadataSuggestion(
        query_title="Test Serie",
        query_year=None,
        tmdb_id=43,
        name="Test Serie: Zweiter Teil",
        original_name="Test Serie: Zweiter Teil",
        first_air_year=2024,
    )

    assert suggestion.folder_name == "Test Serie Zweiter Teil (2024)"


def test_parse_series_query_removes_episode_and_extracts_year():
    from dragontools.core.online_metadata import parse_series_query

    parsed = parse_series_query("Frieren.2023.S02E01.German.Subbed.1080p.WEB.H264.mkv")

    assert parsed.title == "Frieren"
    assert parsed.year == 2023


def test_tmdb_client_requires_credentials():
    from dragontools.core.online_metadata import (
        OnlineMetadataAuthError,
        OnlineMetadataConfig,
        TmdbClient,
    )

    with pytest.raises(OnlineMetadataAuthError):
        TmdbClient(OnlineMetadataConfig(tmdb_enabled=True))


def test_thetvdb_client_resolves_episode_with_login_token(tmp_path):
    from dragontools.core.online_metadata import OnlineMetadataConfig, TheTvdbClient

    posts: list[dict] = []
    gets: list[str] = []

    def fake_post(url: str, headers: dict[str, str], payload: dict, timeout: int):
        posts.append(payload)
        assert url.endswith("/login")
        assert payload["apikey"] == "api"
        assert payload["pin"] == "pin"
        return {"data": {"token": "tvdb-token"}}

    def fake_get(url: str, headers: dict[str, str], timeout: int):
        gets.append(url)
        assert headers["Authorization"] == "Bearer tvdb-token"
        parsed = urlparse(url)
        if parsed.path.endswith("/search"):
            return {
                "data": [
                    {
                        "id": 100,
                        "name": "Stargate Atlantis",
                        "year": "2004",
                        "score": 100,
                    }
                ]
            }
        if parsed.path.endswith("/series/100/extended"):
            return {
                "data": {
                    "id": 100,
                    "name": "Stargate Atlantis",
                    "firstAired": "2004-07-16",
                    "overview": "Atlantis Expedition",
                }
            }
        if parsed.path.endswith("/series/100/episodes/default/deu"):
            return {
                "data": {
                    "episodes": [
                        {
                            "id": 5001,
                            "seasonNumber": 1,
                            "number": 15,
                            "name": "10.000 Jahre",
                            "overview": "Ein alter Sprung.",
                            "aired": "2005-01-31",
                        }
                    ]
                }
            }
        raise AssertionError(url)

    client = TheTvdbClient(
        OnlineMetadataConfig(
            series_provider="thetvdb",
            tvdb_enabled=True,
            tvdb_api_key="api",
            tvdb_pin="pin",
            cache_enabled=False,
        ),
        cache_dir=tmp_path,
        http_get=fake_get,
        http_post=fake_post,
    )

    suggestion = client.resolve_episode_file("Stargate Atlantis - S01E15 - 10.000 Jahre.mkv")

    assert suggestion is not None
    assert suggestion.provider == "thetvdb"
    assert suggestion.series_tmdb_id == 100
    assert suggestion.episode_tmdb_id == 5001
    assert suggestion.title == "10.000 Jahre"
    assert posts == [{"apikey": "api", "pin": "pin"}]
    assert any("/search" in url for url in gets)


def test_thetvdb_client_finds_specials_in_season_zero(tmp_path):
    from dragontools.core.online_metadata import OnlineMetadataConfig, TheTvdbClient

    def fake_get(url: str, headers: dict[str, str], timeout: int):
        parsed = urlparse(url)
        if parsed.path.endswith("/search"):
            return {
                "data": [
                    {
                        "id": 354198,
                        "name": "Kaguya-sama: Love Is War",
                        "year": "2019",
                        "score": 100,
                    }
                ]
            }
        if parsed.path.endswith("/series/354198/extended"):
            return {
                "data": {
                    "id": 354198,
                    "name": "Kaguya-sama: Love Is War",
                    "firstAired": "2019-01-12",
                }
            }
        if parsed.path.endswith("/series/354198/episodes/default/deu"):
            return {
                "data": {
                    "episodes": [
                        {
                            "id": 9706323,
                            "seasonNumber": 0,
                            "number": 5,
                            "name": "Ueber Kaguya Shinomiya, Teil 3",
                        }
                    ]
                }
            }
        raise AssertionError(url)

    client = TheTvdbClient(
        OnlineMetadataConfig(
            series_provider="thetvdb",
            tvdb_enabled=True,
            tvdb_bearer_token="tvdb-token",
            cache_enabled=False,
        ),
        cache_dir=tmp_path,
        http_get=fake_get,
    )

    suggestion = client.resolve_episode_file(
        "Kaguya-sama Love is War (2019) - S00E05.mkv"
    )

    assert suggestion is not None
    assert suggestion.season_number == 0
    assert suggestion.episode_number == 5
    assert suggestion.episode_tmdb_id == 9706323
    assert suggestion.title == "Ueber Kaguya Shinomiya, Teil 3"


def test_thetvdb_client_resolves_movie_with_login_token(tmp_path):
    from dragontools.core.online_metadata import OnlineMetadataConfig, TheTvdbClient

    def fake_post(url: str, headers: dict[str, str], payload: dict, timeout: int):
        assert url.endswith("/login")
        return {"data": {"token": "tvdb-token"}}

    def fake_get(url: str, headers: dict[str, str], timeout: int):
        assert headers["Authorization"] == "Bearer tvdb-token"
        parsed = urlparse(url)
        if parsed.path.endswith("/search"):
            return {
                "data": [
                    {
                        "objectID": "movie-222",
                        "name": "Test Film",
                        "year": "2024",
                        "score": 99,
                    }
                ]
            }
        if parsed.path.endswith("/movies/222/extended"):
            return {
                "data": {
                    "id": 222,
                    "name": "Test Film",
                    "originalName": "Original Test Film",
                    "first_release": "2024-02-03",
                    "overview": "Beschreibung",
                    "remote_ids": [{"sourceName": "IMDB", "id": "tt1234567"}],
                }
            }
        raise AssertionError(url)

    client = TheTvdbClient(
        OnlineMetadataConfig(
            movie_provider="thetvdb",
            tvdb_enabled=True,
            tvdb_api_key="api",
            cache_enabled=False,
        ),
        cache_dir=tmp_path,
        http_get=fake_get,
        http_post=fake_post,
    )

    suggestion = client.resolve_movie("Test Film", year=2024)

    assert suggestion is not None
    assert suggestion.provider == "thetvdb"
    assert suggestion.provider_id == 222
    assert suggestion.movie_folder_name == "Test Film (2024)"
    assert suggestion.imdb_id == "tt1234567"


def test_both_provider_uses_available_source_without_blocking_missing_second_source():
    from dragontools.core.online_metadata import (
        OnlineMetadataConfig,
        client_from_config,
        metadata_provider_configured,
    )

    config = OnlineMetadataConfig(
        movie_provider="both",
        series_provider="both",
        tmdb_enabled=True,
        tmdb_read_token="token",
        tvdb_enabled=False,
    )

    assert config.provider_chain_for("movie") == ("tmdb", "thetvdb")
    assert metadata_provider_configured(config, "movie") is True
    assert metadata_provider_configured(config, "series") is True
    assert client_from_config(config, "movie").provider_label == "TMDB"


def test_both_provider_honors_series_preference():
    from dragontools.core.online_metadata import OnlineMetadataConfig

    config = OnlineMetadataConfig(
        series_provider="both",
        series_preferred_provider="thetvdb",
    )

    assert config.provider_chain_for("series") == ("thetvdb", "tmdb")


def test_thetvdb_series_uses_fallback_translation_instead_of_original_japanese_name(tmp_path):
    from dragontools.core.online_metadata import OnlineMetadataConfig, TheTvdbClient

    def fake_post(url: str, headers: dict[str, str], payload: dict, timeout: int):
        assert url.endswith("/login")
        return {"data": {"token": "tvdb-token"}}

    def fake_get(url: str, headers: dict[str, str], timeout: int):
        assert headers["Authorization"] == "Bearer tvdb-token"
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        if parsed.path.endswith("/search"):
            assert params.get("language") == ["deu"]
            return {
                "data": [
                    {
                        "id": 777,
                        "name": "天幕のジャードゥーガル",
                        # TVDB kann bei fehlender DE-Übersetzung den Originaltitel
                        # auch in name_translated zurückgeben.
                        "name_translated": "天幕のジャードゥーガル",
                        "year": "2025",
                        "score": 100,
                    }
                ]
            }
        if parsed.path.endswith("/series/777/extended"):
            assert params.get("meta") == ["translations"]
            return {
                "data": {
                    "id": 777,
                    "name": "天幕のジャードゥーガル",
                    "firstAired": "2025-07-01",
                    "translations": {
                        "nameTranslations": [
                            {
                                "language": "eng",
                                "name": "Jaadugar: A Witch in Mongolia",
                            },
                            {
                                "language": "jpn",
                                "name": "天幕のジャードゥーガル",
                            },
                        ]
                    },
                }
            }
        raise AssertionError(url)

    client = TheTvdbClient(
        OnlineMetadataConfig(
            series_provider="thetvdb",
            tvdb_enabled=True,
            tvdb_api_key="api",
            language="de-DE",
            fallback_language="en-US",
            cache_enabled=False,
        ),
        cache_dir=tmp_path,
        http_get=fake_get,
        http_post=fake_post,
    )

    suggestion = client.resolve_series("Jaadugar A Witch in Mongolia")

    assert suggestion is not None
    assert suggestion.name == "Jaadugar: A Witch in Mongolia"
    assert suggestion.original_name == "天幕のジャードゥーガル"


def test_tmdb_missing_episode_title_uses_folge_fallback_not_source_filename(tmp_path):
    from dragontools.core.online_metadata import OnlineMetadataConfig, TmdbClient

    def fake_get(url: str, headers: dict[str, str], timeout: int):
        parsed = urlparse(url)
        if parsed.path.endswith("/search/tv"):
            return {
                "results": [
                    {
                        "id": 1433,
                        "name": "American Dad!",
                        "original_name": "American Dad!",
                        "first_air_date": "2005-02-06",
                        "popularity": 100,
                    }
                ]
            }
        if parsed.path.endswith("/tv/1433/season/22/episode/10"):
            return {
                "id": 999999,
                "name": "",
                "overview": "",
                "air_date": "",
                "credits": {},
                "external_ids": {},
            }
        raise AssertionError(url)

    client = TmdbClient(
        OnlineMetadataConfig(tmdb_enabled=True, tmdb_read_token="token", cache_enabled=False),
        cache_dir=tmp_path,
        http_get=fake_get,
    )

    suggestions = client.resolve_episode_candidates(
        "american.dad.s22e10.german.dl.1080p.web.h264-wayne.mkv"
    )

    assert suggestions
    assert suggestions[0].title == "Folge 10"
    assert suggestions[0].title_is_fallback is True
    assert "american.dad.s22e10" not in suggestions[0].title.lower()


def test_tvdb_missing_episode_title_uses_folge_fallback_not_source_filename(tmp_path):
    from dragontools.core.online_metadata import OnlineMetadataConfig, TheTvdbClient

    def fake_post(url: str, headers: dict[str, str], payload: dict, timeout: int):
        return {"data": {"token": "tvdb-token"}}

    def fake_get(url: str, headers: dict[str, str], timeout: int):
        parsed = urlparse(url)
        if parsed.path.endswith("/search"):
            return {
                "data": [
                    {
                        "id": 73141,
                        "name": "American Dad!",
                        "year": "2005",
                        "score": 100,
                    }
                ]
            }
        if parsed.path.endswith("/series/73141/extended"):
            return {
                "data": {
                    "id": 73141,
                    "name": "American Dad!",
                    "firstAired": "2005-02-06",
                }
            }
        if "/series/73141/episodes/default/" in parsed.path:
            return {
                "data": {
                    "episodes": [
                        {
                            "id": 999999,
                            "seasonNumber": 22,
                            "number": 10,
                            "name": "",
                        }
                    ]
                }
            }
        raise AssertionError(url)

    client = TheTvdbClient(
        OnlineMetadataConfig(
            series_provider="thetvdb",
            tvdb_enabled=True,
            tvdb_api_key="api",
            cache_enabled=False,
        ),
        cache_dir=tmp_path,
        http_get=fake_get,
        http_post=fake_post,
    )

    suggestions = client.resolve_episode_candidates(
        "american.dad.s22e10.german.dl.1080p.web.h264-wayne.mkv"
    )

    assert suggestions
    assert suggestions[0].title == "Folge 10"
    assert suggestions[0].title_is_fallback is True
    assert "american.dad.s22e10" not in suggestions[0].title.lower()


def test_generic_provider_episode_titles_are_normalized_to_german_fallback():
    from dragontools.core.online_metadata import normalize_episode_metadata_title

    for raw in ("Episode 10", "Ep. 10", "Folge 10", "S22E10"):
        title, is_fallback = normalize_episode_metadata_title(raw, 10)
        assert title == "Folge 10"
        assert is_fallback is True

    title, is_fallback = normalize_episode_metadata_title("A Roger Story", 10)
    assert title == "A Roger Story"
    assert is_fallback is False
