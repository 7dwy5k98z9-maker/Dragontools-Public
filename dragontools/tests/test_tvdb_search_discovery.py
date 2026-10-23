"""Regression coverage for TVDB series lost before renamer selection."""
from urllib.parse import parse_qs, urlparse

from dragontools.core.movie_renamer import build_series_rename_proposal
from dragontools.core.online_metadata import OnlineMetadataConfig, TheTvdbClient


def _client(tmp_path, http_get, **overrides):
    config = dict(
        series_provider="thetvdb", tvdb_enabled=True,
        tvdb_bearer_token="offline-test-token", cache_enabled=False,
        language="de-DE", fallback_language="en-US",
    )
    config.update(overrides)
    return TheTvdbClient(OnlineMetadataConfig(**config), cache_dir=tmp_path, http_get=http_get)


def _keroro():
    return {
        "id": "series-472037", "tvdb_id": "472037", "name": "KERORO☆",
        "year": "2026", "translations": {"deu": "KERORO☆", "eng": "KERORO☆"},
    }


def _details(url):
    path = urlparse(url).path
    if path.endswith("/series/322266/extended"):
        return {"data": {"id": 322266, "name": "Il tesoro di Damasco", "firstAired": "2010-01-01"}}
    if path.endswith("/series/472037/extended"):
        return {"data": {"id": 472037, "name": "KERORO☆", "firstAired": "2026-10-03"}}
    if path.endswith("/series/472037/episodes/default/deu"):
        return {"data": {"episodes": [{
            "id": 12000003, "seasonNumber": 1, "number": 3,
            "name": "Das Geheimnis der beiden", "aired": "2026-10-17",
        }]}}
    raise AssertionError(url)


def test_explicit_year_is_applied_before_the_provider_limits_results(tmp_path):
    """A remake outside ten broad hits must survive server-side discovery."""
    requests = []
    unrelated = [
        {"id": f"series-{1000 + index}", "name": f"Unrelated {index}", "year": "2014"}
        for index in range(10)
    ]

    def get(url, *_args):
        if urlparse(url).path.endswith("/search"):
            params = parse_qs(urlparse(url).query)
            requests.append(params)
            records = [_keroro()] if params.get("year") == ["2026"] else unrelated + [_keroro()]
            return {"data": records[:int(params["limit"][0])]}
        return _details(url)

    client = _client(tmp_path, get)
    hits = client.search_series("KERORO", year=2026)
    assert [hit["provider_id"] for hit in hits] == [472037]
    assert requests[0]["year"] == ["2026"]
    assert requests[0]["language"] == ["deu"]


def test_broad_search_can_find_a_series_after_ten_unrelated_hits(tmp_path):
    def get(url, *_args):
        params = parse_qs(urlparse(url).query)
        records = [
            {"id": f"series-{1000 + index}", "name": f"Unrelated {index}", "year": "2014"}
            for index in range(10)
        ] + [_keroro()]
        return {"data": records[:int(params["limit"][0])]}

    hits = _client(tmp_path, get).search_series("KERORO")
    assert 472037 in [hit["provider_id"] for hit in hits]


def test_unrelated_primary_results_do_not_hide_fallback_keroro_in_renamer(tmp_path):
    languages = []

    def get(url, *_args):
        if urlparse(url).path.endswith("/search"):
            language = parse_qs(urlparse(url).query)["language"][0]
            languages.append(language)
            if language == "deu":
                # Like the saved response: unknown-year false positives remain
                # nonempty even after the local year filter has run.
                return {"data": [{"id": "series-322266", "name": "Il tesoro di Damasco"}]}
            return {"data": [_keroro()]}
        return _details(url)

    client = _client(tmp_path, get)
    path = "KERORO.2026.S01E03.German.Subbed.ANiME.AAC.1080p.CR.WEB.H264-DRiFTKiNG.mkv"
    proposal = build_series_rename_proposal(path, client=client)
    assert proposal.selected is not None
    assert proposal.selected.provider == "thetvdb"
    assert proposal.selected.provider_id == 472037
    assert proposal.selected.year == 2026
    assert proposal.selected.episode_title == "Das Geheimnis der beiden"
    assert "deu" in languages and "eng" in languages
    count = len(languages)
    again = client.resolve_renamer_episode_candidates(path)
    assert again and again[0].series_provider_id == 472037
    assert len(languages) == count


def test_primary_and_fallback_candidates_are_merged_without_duplicates(tmp_path):
    def get(url, *_args):
        language = parse_qs(urlparse(url).query)["language"][0]
        old = {"id": "series-268196", "tvdb_id": "268196", "name": "Keroro", "year": "2014"}
        return {"data": [old] if language == "deu" else [old, _keroro()]}

    from dragontools.core.online_metadata_tvdb_candidate_cache import collect_candidate_records
    request = {"query": "KERORO", "year": None, "search_terms": ("KERORO",), "retry_without_year": False}
    hits = collect_candidate_records(_client(tmp_path, get), request)
    assert [hit["provider_id"] for hit in hits] == [268196, 472037]
