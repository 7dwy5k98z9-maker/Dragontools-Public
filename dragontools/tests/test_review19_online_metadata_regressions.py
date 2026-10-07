from __future__ import annotations

from email.message import Message
from io import BytesIO
from pathlib import Path
from threading import RLock
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request
import json
import xml.etree.ElementTree as ET

import pytest


def _cfg(**overrides):
    from dragontools.core.online_metadata import OnlineMetadataConfig

    values = dict(
        tmdb_enabled=True,
        tmdb_read_token="tmdb-token",
        tvdb_enabled=True,
        tvdb_api_key="tvdb-key",
        language="de-DE",
        fallback_language="en-US",
        cache_enabled=False,
    )
    values.update(overrides)
    return OnlineMetadataConfig(**values)


def test_unicode_metadata_normalization_keeps_non_latin_titles():
    from dragontools.core.online_metadata_parsing import compare_metadata_text

    assert compare_metadata_text("劇場版モノノ怪") == "劇場版モノノ怪"
    assert compare_metadata_text("咒術迴戰") != compare_metadata_text("劇場版モノノ怪")


def test_tmdb_unicode_episode_rank_can_be_exact():
    from dragontools.core.online_metadata_parsing import compare_metadata_text
    from dragontools.core.online_metadata_tmdb_suggestions import TmdbSuggestionMixin

    rank = TmdbSuggestionMixin._episode_candidate_rank(
        {"id": 1, "name": "劇場版モノノ怪", "original_name": "劇場版モノノ怪"},
        query_norm=compare_metadata_text("劇場版モノノ怪"),
        query_year=None,
    )
    assert rank[0] == pytest.approx(1.0)


def test_tvdb_unicode_candidate_rank_can_be_exact():
    from dragontools.core.online_metadata_tvdb_candidates import _record_rank

    client = SimpleNamespace(config=_cfg())
    rank = _record_rank(
        client,
        {"id": 7, "name": "薬屋のひとりごと", "score": 42},
        query="薬屋のひとりごと",
        year=None,
    )
    assert rank[0] == pytest.approx(1.0)


def test_postprocess_unicode_confidence_gate_can_be_exact():
    from dragontools.worker.postprocess_metadata_resolution import _text_score

    assert _text_score("劇場版モノノ怪", "劇場版モノノ怪") == pytest.approx(1.0)


def test_tmdb_candidate_transient_failure_does_not_poison_session_cache():
    from dragontools.core.online_metadata import OnlineMetadataError
    from dragontools.core.online_metadata_tmdb_candidate_cache import collect_episode_candidate_records

    class Client:
        config = _cfg()
        _renamer_search_cache = {}
        _renamer_batch_lock = RLock()

        def __init__(self):
            self.fail = True
            self.calls = 0

        def search_tv(self, _term, *, year=None, language=None):
            self.calls += 1
            if self.fail:
                raise OnlineMetadataError("temporär")
            return [{"id": 11, "name": "Frieren"}]

    client = Client()
    with pytest.raises(OnlineMetadataError):
        collect_episode_candidate_records(
            client, "Frieren", year=None, search_terms=("Frieren",), retry_without_year=False
        )
    assert client._renamer_search_cache == {}

    client.fail = False
    result = collect_episode_candidate_records(
        client, "Frieren", year=None, search_terms=("Frieren",), retry_without_year=False
    )
    assert [item["id"] for item in result] == [11]
    assert client.calls >= 2


def test_tvdb_candidate_transient_failure_does_not_poison_session_cache():
    from dragontools.core.online_metadata import OnlineMetadataError
    from dragontools.core.online_metadata_tvdb_candidate_cache import collect_candidate_records

    class Client:
        config = _cfg()
        _renamer_search_cache = {}
        _episode_batch_lock = RLock()

        def __init__(self):
            self.fail = True
            self.calls = 0

        def search_series(self, _term, *, year=None, language=None):
            self.calls += 1
            if self.fail:
                raise OnlineMetadataError("temporär")
            return [{"id": 21, "name": "Frieren"}]

    request = {
        "query": "Frieren",
        "year": None,
        "search_terms": ("Frieren",),
        "retry_without_year": False,
    }
    client = Client()
    with pytest.raises(OnlineMetadataError):
        collect_candidate_records(client, request)
    assert client._renamer_search_cache == {}

    client.fail = False
    assert [item["id"] for item in collect_candidate_records(client, request)] == [21]
    assert client.calls >= 2


def test_tmdb_partial_failure_returns_records_but_does_not_cache_them():
    from dragontools.core.online_metadata import OnlineMetadataError
    from dragontools.core.online_metadata_tmdb_candidate_cache import collect_episode_candidate_records

    class Client:
        config = _cfg(fallback_language="de-DE")
        _renamer_search_cache = {}
        _renamer_batch_lock = RLock()

        def search_tv(self, term, *, year=None, language=None):
            if term == "alt":
                raise OnlineMetadataError("zweite Dimension fehlgeschlagen")
            return [{"id": 31, "name": "Main"}]

    client = Client()
    result = collect_episode_candidate_records(
        client,
        "Main",
        year=None,
        search_terms=("main", "alt"),
        retry_without_year=False,
    )
    assert [item["id"] for item in result] == [31]
    assert client._renamer_search_cache == {}


def test_http_404_is_distinguished_from_generic_provider_error(monkeypatch):
    import dragontools.core.online_metadata_http as http
    from dragontools.core.online_metadata import OnlineMetadataError

    def fail(_request, timeout):
        raise HTTPError(
            "https://example.invalid/missing",
            404,
            "Not Found",
            Message(),
            BytesIO(b'{"status_message":"missing"}'),
        )

    monkeypatch.setattr(http, "urlopen", fail)
    with pytest.raises(OnlineMetadataError) as exc_info:
        http.request_json(Request("https://example.invalid/missing"), 1, label="TMDB")

    assert exc_info.value.__class__.__name__ == "OnlineMetadataNotFoundError"


def test_malformed_json_is_non_retryable_response_error(monkeypatch):
    import dragontools.core.online_metadata_http as http
    from dragontools.core.online_metadata_retry import RetryableOnlineMetadataError

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b"{not-json"

    monkeypatch.setattr(http, "urlopen", lambda _request, timeout: Response())
    with pytest.raises(Exception) as exc_info:
        http.request_json(Request("https://example.invalid"), 1, label="TMDB")

    assert exc_info.value.__class__.__name__ == "OnlineMetadataResponseError"
    assert not isinstance(exc_info.value, RetryableOnlineMetadataError)


def test_top_level_json_array_is_rejected_as_malformed_response(monkeypatch):
    import dragontools.core.online_metadata_http as http

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b"[]"

    monkeypatch.setattr(http, "urlopen", lambda _request, timeout: Response())
    with pytest.raises(Exception) as exc_info:
        http.request_json(Request("https://example.invalid"), 1, label="TMDB")
    assert exc_info.value.__class__.__name__ == "OnlineMetadataResponseError"


def test_tmdb_invalid_success_payload_is_not_cached(tmp_path):
    from dragontools.core.online_metadata import TmdbClient

    responses = iter(({"results": "broken"}, {"results": []}))
    calls = 0

    def fake_get(_url, _headers, _timeout):
        nonlocal calls
        calls += 1
        return next(responses)

    client = TmdbClient(_cfg(tvdb_enabled=False), cache_dir=tmp_path, http_get=fake_get)
    with pytest.raises(Exception) as exc_info:
        client.search_movies("Test")
    assert exc_info.value.__class__.__name__ == "OnlineMetadataResponseError"

    assert client.search_movies("Test") == []
    assert calls == 2


def test_tvdb_expired_bearer_reauthenticates_once_with_api_key(tmp_path):
    from dragontools.core.online_metadata import OnlineMetadataAuthError, TheTvdbClient

    gets: list[str] = []
    posts = 0

    def fake_get(_url, headers, _timeout):
        token = headers.get("Authorization", "")
        gets.append(token)
        if token == "Bearer stale-token":
            raise OnlineMetadataAuthError("expired")
        assert token == "Bearer fresh-token"
        return {"data": []}

    def fake_post(_url, _headers, payload, _timeout):
        nonlocal posts
        posts += 1
        assert payload["apikey"] == "tvdb-key"
        return {"data": {"token": "fresh-token"}}

    client = TheTvdbClient(
        _cfg(tmdb_enabled=False, tvdb_bearer_token="stale-token"),
        cache_dir=tmp_path,
        http_get=fake_get,
        http_post=fake_post,
    )
    assert client.search_series("Test") == []
    assert gets == ["Bearer stale-token", "Bearer fresh-token"]
    assert posts == 1


def test_tvdb_bearer_only_auth_failure_does_not_attempt_login(tmp_path):
    from dragontools.core.online_metadata import OnlineMetadataAuthError, TheTvdbClient

    posts = 0

    def fake_get(_url, _headers, _timeout):
        raise OnlineMetadataAuthError("expired")

    def fake_post(*_args):
        nonlocal posts
        posts += 1
        raise AssertionError("Bearer-only client must not try /login without API key")

    client = TheTvdbClient(
        _cfg(
            tmdb_enabled=False,
            tvdb_api_key="",
            tvdb_bearer_token="stale-token",
        ),
        cache_dir=tmp_path,
        http_get=fake_get,
        http_post=fake_post,
    )
    with pytest.raises(OnlineMetadataAuthError):
        client.search_series("Test")
    assert posts == 0


def test_tvdb_language_code_strips_bcp47_region_before_mapping():
    from dragontools.core.online_metadata_tvdb_helpers import _tvdb_language_code

    assert _tvdb_language_code("zh-CN") == "zho"
    assert _tvdb_language_code("pt-BR") == "por"
    assert _tvdb_language_code("de-DE") == "deu"


def test_tmdb_explicit_year_never_falls_back_to_wrong_remake(tmp_path):
    from dragontools.core.online_metadata import TmdbClient

    detail_calls = 0

    def fake_get(url, _headers, _timeout):
        nonlocal detail_calls
        if "/search/movie" in url:
            return {
                "results": [
                    {"id": 99, "title": "The Thing", "original_title": "The Thing", "release_date": "1982-06-25"}
                ]
            }
        detail_calls += 1
        return {"id": 99, "title": "The Thing", "release_date": "1982-06-25"}

    client = TmdbClient(_cfg(tvdb_enabled=False), cache_dir=tmp_path, http_get=fake_get)
    assert client.resolve_movie("The Thing", year=2011) is None
    assert detail_calls == 0


def test_tvdb_explicit_year_never_falls_back_to_wrong_remake(tmp_path):
    from dragontools.core.online_metadata import TheTvdbClient

    detail_calls = 0

    def fake_get(url, _headers, _timeout):
        nonlocal detail_calls
        if "/search?" in url:
            return {"data": [{"id": 77, "name": "Shōgun", "year": "1980"}]}
        detail_calls += 1
        return {"data": {"id": 77, "name": "Shōgun", "year": "1980"}}

    client = TheTvdbClient(
        _cfg(tmdb_enabled=False, tvdb_bearer_token="token"),
        cache_dir=tmp_path,
        http_get=fake_get,
        http_post=lambda *_args: {"data": {"token": "unused"}},
    )
    assert client.resolve_series("Shōgun", year=2024) is None
    assert detail_calls == 0


def test_tmdb_partial_search_record_without_id_is_ignored(tmp_path):
    from dragontools.core.online_metadata import TmdbClient

    def fake_get(url, _headers, _timeout):
        if "/search/movie" in url:
            return {
                "results": [
                    {"title": "Dune", "release_date": "2021-01-01"},
                    {"id": 438631, "title": "Dune", "original_title": "Dune", "release_date": "2021-10-22"},
                ]
            }
        if "/movie/438631" in url:
            return {
                "id": 438631,
                "title": "Dune",
                "original_title": "Dune",
                "release_date": "2021-10-22",
            }
        raise AssertionError(url)

    client = TmdbClient(_cfg(tvdb_enabled=False), cache_dir=tmp_path, http_get=fake_get)
    result = client.resolve_movie("Dune", year=2021)
    assert result is not None
    assert result.tmdb_id == 438631


def test_tmdb_detail_identity_mismatch_is_rejected(tmp_path):
    from dragontools.core.online_metadata import TmdbClient

    def fake_get(url, _headers, _timeout):
        if "/search/movie" in url:
            return {"results": [{"id": 1, "title": "Test", "release_date": "2024-01-01"}]}
        if "/movie/1" in url:
            return {"id": 2, "title": "Other", "release_date": "2024-01-01"}
        raise AssertionError(url)

    client = TmdbClient(_cfg(tvdb_enabled=False), cache_dir=tmp_path, http_get=fake_get)
    with pytest.raises(Exception) as exc_info:
        client.resolve_movie("Test", year=2024)
    assert exc_info.value.__class__.__name__ == "OnlineMetadataResponseError"


def test_tvdb_movie_nfo_keeps_provider_id_out_of_tmdb_fields(tmp_path):
    from dragontools.core.jellyfin_nfo import write_movie_nfo
    from dragontools.core.online_metadata import MovieMetadataSuggestion

    suggestion = MovieMetadataSuggestion(
        query_title="Movie",
        query_year=2024,
        tmdb_id=12345,  # compatibility field carries provider ID for TVDB suggestions
        title="Movie",
        original_title="Movie",
        release_year=2024,
        provider="thetvdb",
        provider_id=12345,
    )
    path = tmp_path / "movie.nfo"
    write_movie_nfo(path, suggestion, include_fileinfo=False)
    root = ET.parse(path).getroot()

    assert root.findtext("tvdbid") == "12345"
    assert root.find("tmdbid") is None
    unique = {(node.get("type"), node.text) for node in root.findall("uniqueid")}
    assert ("tvdb", "12345") in unique
    assert not any(kind == "tmdb" for kind, _value in unique)


def test_tvdb_detail_transport_failure_is_not_downgraded_to_partial_movie():
    from dragontools.core.online_metadata import OnlineMetadataError
    from dragontools.core.online_metadata_tvdb_suggestions import TvdbSuggestionMixin

    class Client(TvdbSuggestionMixin):
        config = _cfg()

        def movie_details(self, *_args, **_kwargs):
            raise OnlineMetadataError("TVDB 503 after retries")

    with pytest.raises(OnlineMetadataError, match="503"):
        Client()._movie_suggestion_from_record(
            "Film", 2024, {"id": 12, "name": "Film", "year": "2024"}
        )


def test_tmdb_episode_transport_failure_is_not_downgraded_to_no_result(tmp_path):
    from dragontools.core.online_metadata import OnlineMetadataError
    from dragontools.core.online_metadata_tmdb_suggestions import TmdbSuggestionMixin

    class Client(TmdbSuggestionMixin):
        def tv_episode_details(self, *_args, **_kwargs):
            raise OnlineMetadataError("TMDB 429 after retries")

    with pytest.raises(OnlineMetadataError, match="429"):
        Client()._episode_suggestion_from_candidate(
            {"id": 5, "name": "Serie"},
            path=tmp_path / "Serie - S01E01.mkv",
            query="Serie",
            query_year=None,
            season=1,
            episode=1,
        )


def test_tmdb_renamer_season_transport_failure_is_not_silently_fallbacked():
    from dragontools.core.online_metadata import OnlineMetadataError
    from dragontools.core.online_metadata_tmdb_renamer import TmdbRenamerBatchMixin

    class Client(TmdbRenamerBatchMixin):
        def tv_season_details(self, *_args, **_kwargs):
            raise OnlineMetadataError("TMDB timeout after retries")

    with pytest.raises(OnlineMetadataError, match="timeout"):
        Client()._renamer_episode_from_season(1, 1, 1)


def test_tvdb_episode_candidate_preserves_provider_error_instead_of_nameerror(tmp_path):
    from dragontools.core.online_metadata import OnlineMetadataError, SeriesMetadataSuggestion
    from dragontools.core.online_metadata_tvdb_candidates import _build_suggestion

    class Client:
        def resolve_episode_record(self, *_args, **_kwargs):
            raise OnlineMetadataError("TVDB timeout after retries")

    series = SeriesMetadataSuggestion(
        query_title="Serie",
        query_year=None,
        tmdb_id=44,
        name="Serie",
        original_name="Serie",
        first_air_year=2024,
        provider="thetvdb",
        provider_id=44,
    )

    with pytest.raises(OnlineMetadataError, match="timeout"):
        _build_suggestion(
            Client(),
            path=tmp_path / "Serie - S01E01.mkv",
            request={"query": "Serie", "year": None, "season": 1, "episode": 1},
            record={"id": 44, "name": "Serie"},
            series_builder=lambda *_args, **_kwargs: series,
        )


def test_tmdb_missing_search_year_can_be_verified_from_details(tmp_path):
    from dragontools.core.online_metadata import TmdbClient

    def fake_get(url, _headers, _timeout):
        if "/search/movie" in url:
            return {"results": [{"id": 500, "title": "Partial"}]}
        if "/movie/500" in url:
            return {
                "id": 500,
                "title": "Partial",
                "original_title": "Partial",
                "release_date": "2024-03-01",
            }
        raise AssertionError(url)

    client = TmdbClient(_cfg(tvdb_enabled=False), cache_dir=tmp_path, http_get=fake_get)
    result = client.resolve_movie("Partial", year=2024)
    assert result is not None
    assert result.release_year == 2024


def test_tvdb_missing_search_year_can_be_verified_from_details(tmp_path):
    from dragontools.core.online_metadata import TheTvdbClient

    def fake_get(url, _headers, _timeout):
        if "/search?" in url:
            return {"data": [{"id": 501, "name": "Partial"}]}
        if "/series/501/extended" in url:
            return {"data": {"id": 501, "name": "Partial", "firstAired": "2024-01-10"}}
        raise AssertionError(url)

    client = TheTvdbClient(
        _cfg(tmdb_enabled=False, tvdb_bearer_token="token"),
        cache_dir=tmp_path,
        http_get=fake_get,
        http_post=lambda *_args: {"data": {"token": "unused"}},
    )
    result = client.resolve_series("Partial", year=2024)
    assert result is not None
    assert result.first_air_year == 2024


def test_tmdb_unknown_final_year_is_rejected_for_explicit_year(tmp_path):
    from dragontools.core.online_metadata import TmdbClient

    def fake_get(url, _headers, _timeout):
        if "/search/movie" in url:
            return {"results": [{"id": 502, "title": "Unknown Year"}]}
        if "/movie/502" in url:
            return {"id": 502, "title": "Unknown Year", "original_title": "Unknown Year"}
        raise AssertionError(url)

    client = TmdbClient(_cfg(tvdb_enabled=False), cache_dir=tmp_path, http_get=fake_get)
    assert client.resolve_movie("Unknown Year", year=2024) is None


def test_tvdb_name_translated_dict_uses_requested_language_not_hardcoded_english():
    from dragontools.core.online_metadata_tvdb_helpers import _tvdb_localized_title

    record = {
        "name": "原題",
        "name_translated": {"eng": "English title", "spa": "Título español"},
    }
    assert _tvdb_localized_title(record, "es-ES") == "Título español"


def test_tvdb_localized_overview_prefers_requested_translation():
    from dragontools.core.online_metadata_tvdb_helpers import _tvdb_localized_overview

    record = {
        "overview": "Original overview",
        "translations": {
            "overviewTranslations": [
                {"language": "eng", "overview": "English overview"},
                {"language": "deu", "overview": "Deutsche Beschreibung"},
            ]
        },
    }
    assert _tvdb_localized_overview(record, "de-DE") == "Deutsche Beschreibung"


def test_tmdb_direct_resolver_rejects_unrelated_same_year_result(tmp_path):
    from dragontools.core.online_metadata import TmdbClient

    detail_calls = 0

    def fake_get(url, _headers, _timeout):
        nonlocal detail_calls
        if "/search/movie" in url:
            return {"results": [{"id": 700, "title": "Completely Different", "release_date": "2024-01-01"}]}
        detail_calls += 1
        return {"id": 700, "title": "Completely Different", "release_date": "2024-01-01"}

    client = TmdbClient(_cfg(tvdb_enabled=False), cache_dir=tmp_path, http_get=fake_get)
    assert client.resolve_movie("Totally Unrelated", year=2024) is None
    assert detail_calls == 1


def test_tvdb_direct_resolver_rejects_unrelated_same_year_result(tmp_path):
    from dragontools.core.online_metadata import TheTvdbClient

    detail_calls = 0

    def fake_get(url, _headers, _timeout):
        nonlocal detail_calls
        if "/search?" in url:
            return {"data": [{"id": 701, "name": "Completely Different", "year": "2024"}]}
        detail_calls += 1
        return {"data": {"id": 701, "name": "Completely Different", "year": "2024"}}

    client = TheTvdbClient(
        _cfg(tmdb_enabled=False, tvdb_bearer_token="token"),
        cache_dir=tmp_path,
        http_get=fake_get,
        http_post=lambda *_args: {"data": {"token": "unused"}},
    )
    assert client.resolve_series("Totally Unrelated", year=2024) is None
    assert detail_calls == 1


def test_tvdb_scoring_uses_original_non_latin_title_when_localized_title_differs():
    from dragontools.core.online_metadata_tvdb_candidates import _record_rank

    client = SimpleNamespace(config=_cfg())
    record = {
        "id": 702,
        "name": "Mononoke the Movie",
        "name_translated": "Mononoke the Movie",
        "originalName": "劇場版モノノ怪",
        "year": "2024",
    }
    rank = _record_rank(client, record, query="劇場版モノノ怪", year=2024)
    assert rank[0] == pytest.approx(1.0)


def test_tmdb_title_identity_beats_unrelated_known_year_when_exact_candidate_year_is_partial(tmp_path):
    from dragontools.core.online_metadata import TmdbClient

    def fake_get(url, _headers, _timeout):
        if "/search/movie" in url:
            return {
                "results": [
                    {"id": 800, "title": "Different Movie", "release_date": "2024-01-01"},
                    {"id": 801, "title": "Target Movie"},
                ]
            }
        if "/movie/801" in url:
            return {"id": 801, "title": "Target Movie", "original_title": "Target Movie", "release_date": "2024-05-01"}
        raise AssertionError(url)

    client = TmdbClient(_cfg(tvdb_enabled=False), cache_dir=tmp_path, http_get=fake_get)
    result = client.resolve_movie("Target Movie", year=2024)
    assert result is not None and result.tmdb_id == 801


def test_tvdb_title_identity_beats_unrelated_known_year_when_exact_candidate_year_is_partial(tmp_path):
    from dragontools.core.online_metadata import TheTvdbClient

    def fake_get(url, _headers, _timeout):
        if "/search?" in url:
            return {
                "data": [
                    {"id": 810, "name": "Different Series", "year": "2024"},
                    {"id": 811, "name": "Target Series"},
                ]
            }
        if "/series/811/extended" in url:
            return {"data": {"id": 811, "name": "Target Series", "firstAired": "2024-04-01"}}
        raise AssertionError(url)

    client = TheTvdbClient(
        _cfg(tmdb_enabled=False, tvdb_bearer_token="token"),
        cache_dir=tmp_path,
        http_get=fake_get,
        http_post=lambda *_args: {"data": {"token": "unused"}},
    )
    result = client.resolve_series("Target Series", year=2024)
    assert result is not None and result.provider_id == 811


def test_tmdb_episode_detail_without_id_is_malformed_not_no_result(tmp_path):
    from dragontools.core.online_metadata_tmdb_suggestions import TmdbSuggestionMixin

    class Client(TmdbSuggestionMixin):
        def tv_episode_details(self, *_args, **_kwargs):
            return {"name": "Episode 1"}

    with pytest.raises(Exception) as exc_info:
        Client()._episode_suggestion_from_candidate(
            {"id": 900, "name": "Serie"},
            path=tmp_path / "Serie - S01E01.mkv",
            query="Serie",
            query_year=None,
            season=1,
            episode=1,
        )
    assert exc_info.value.__class__.__name__ == "OnlineMetadataResponseError"


def test_tvdb_episode_candidate_without_id_is_malformed_not_no_result(tmp_path):
    from dragontools.core.online_metadata import SeriesMetadataSuggestion
    from dragontools.core.online_metadata_tvdb_candidates import _build_suggestion

    class Client:
        def resolve_episode_record(self, *_args, **_kwargs):
            return {"name": "Episode 1"}

    series = SeriesMetadataSuggestion(
        query_title="Serie", query_year=None, tmdb_id=901,
        name="Serie", original_name="Serie", first_air_year=2024,
        provider="thetvdb", provider_id=901,
    )
    with pytest.raises(Exception) as exc_info:
        _build_suggestion(
            Client(),
            path=tmp_path / "Serie - S01E01.mkv",
            request={"query": "Serie", "year": None, "season": 1, "episode": 1},
            record={"id": 901, "name": "Serie"},
            series_builder=lambda *_args, **_kwargs: series,
        )
    assert exc_info.value.__class__.__name__ == "OnlineMetadataResponseError"


def test_tvdb_detail_identity_mismatch_is_rejected(tmp_path):
    from dragontools.core.online_metadata import TheTvdbClient

    def fake_get(url, _headers, _timeout):
        if "/search?" in url:
            return {"data": [{"id": 902, "name": "Target", "year": "2024"}]}
        if "/series/902/extended" in url:
            return {"data": {"id": 999, "name": "Target", "firstAired": "2024-01-01"}}
        raise AssertionError(url)

    client = TheTvdbClient(
        _cfg(tmdb_enabled=False, tvdb_bearer_token="token"),
        cache_dir=tmp_path,
        http_get=fake_get,
        http_post=lambda *_args: {"data": {"token": "unused"}},
    )
    with pytest.raises(Exception) as exc_info:
        client.resolve_series("Target", year=2024)
    assert exc_info.value.__class__.__name__ == "OnlineMetadataResponseError"


def test_movie_parser_does_not_treat_numeric_title_as_release_year():
    from dragontools.core.online_metadata import parse_movie_query

    assert parse_movie_query("1917.mkv").year is None
    assert parse_movie_query("1917.mkv").title == "1917"
    blade = parse_movie_query("Blade Runner 2049.mkv")
    assert blade.year is None
    assert blade.title == "Blade Runner 2049"


def test_movie_parser_can_still_extract_real_year_after_numeric_title():
    from dragontools.core.online_metadata import parse_movie_query

    parsed = parse_movie_query("2001.A.Space.Odyssey.1968.BluRay.mkv")
    assert parsed.title == "2001 A Space Odyssey"
    assert parsed.year == 1968


def test_series_parser_does_not_turn_1899_title_into_year_or_episode_filename():
    from dragontools.core.online_metadata import parse_series_query

    parsed = parse_series_query("1899 - S01E01.mkv")
    assert parsed.title == "1899"
    assert parsed.year is None


def test_series_parser_prefers_explicit_release_year_for_numeric_title():
    from dragontools.core.online_metadata import parse_series_query

    parsed = parse_series_query("1923 (2022) - S01E01.mkv")
    assert parsed.title == "1923"
    assert parsed.year == 2022


def test_tvdb_overview_fallback_language_is_used_before_original_text():
    from dragontools.core.online_metadata_tvdb_helpers import _tvdb_localized_overview

    record = {
        "overview": "日本語の概要",
        "translations": {
            "overviewTranslations": [
                {"language": "eng", "overview": "English fallback overview"},
            ]
        },
    }
    assert _tvdb_localized_overview(record, "de-DE") == ""
    assert _tvdb_localized_overview(record, "en-US") == "English fallback overview"


def test_convenience_suggestion_logs_provider_failure(monkeypatch, caplog, tmp_path):
    from dragontools.core import online_metadata_service as service
    from dragontools.core.online_metadata import OnlineMetadataError

    class Client:
        def resolve_movie_file(self, _path):
            raise OnlineMetadataError("HTTP 429 nach Retries")

    monkeypatch.setattr(service, "client_from_settings_for", lambda *_a, **_k: Client())
    caplog.set_level("WARNING")
    assert service.suggest_movie_metadata_for_file(tmp_path / "Film.mkv", object()) is None
    assert "HTTP 429 nach Retries" in caplog.text


def test_tvdb_search_result_provider_identity_cannot_be_spoofed(tmp_path):
    from dragontools.core.online_metadata import TheTvdbClient

    client = TheTvdbClient(
        _cfg(tmdb_enabled=False, tvdb_bearer_token="token"),
        cache_dir=tmp_path,
        http_get=lambda *_args: {
            "data": [{"id": 123, "name": "Target", "provider": "tmdb", "provider_id": 999}]
        },
        http_post=lambda *_args: {"data": {"token": "unused"}},
    )
    result = client.search_series("Target")
    assert result[0]["provider"] == "thetvdb"
    assert result[0]["provider_id"] == 123


def test_tmdb_search_result_provider_identity_is_transport_owned(tmp_path):
    from dragontools.core.online_metadata import TmdbClient

    client = TmdbClient(
        _cfg(tvdb_enabled=False),
        cache_dir=tmp_path,
        http_get=lambda *_args: {
            "results": [{"id": 456, "title": "Target", "provider": "thetvdb", "provider_id": 999}]
        },
    )
    result = client.search_movies("Target")
    assert result[0]["provider"] == "tmdb"
    assert result[0]["provider_id"] == 456
