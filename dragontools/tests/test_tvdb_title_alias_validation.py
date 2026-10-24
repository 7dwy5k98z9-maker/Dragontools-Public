from types import SimpleNamespace

import pytest

from dragontools.core.online_metadata_tvdb_suggestions import TvdbSuggestionMixin
from dragontools.rules import renamer_rules


@pytest.fixture
def alias_rules(monkeypatch):
    monkeypatch.setattr(renamer_rules, "_RULES_CACHE", renamer_rules.migrate_renamer_rules({
        "title_exceptions": [{
            "source": "The Apothecary Diaries",
            "replacement": "Die Tageb\u00fccher der Apothekerin",
        }],
    }))


@pytest.mark.parametrize("query, name, expected", [
    ("The Apothecary Diaries", "Die Tageb\u00fccher der Apothekerin", True),
    ("the.apothecary.diaries", "Die Tageb\u00fccher der Apothekerin", True),
    ("The Apothecary Diaries", "The Apothecary Diaries", True),
    ("The Apothecary Diaries", "Breaking Bad", False),
    ("", "Die Tageb\u00fccher der Apothekerin", False),
])
def test_title_validation_respects_explicit_alias(alias_rules, query, name, expected):
    assert TvdbSuggestionMixin._title_match_is_plausible(query, name) is expected


@pytest.mark.parametrize("year, accepted", [(2023, True), (2024, False)])
def test_series_details_accept_alias_but_still_validate_year(alias_rules, year, accepted):
    class Client(TvdbSuggestionMixin):
        config = SimpleNamespace(language="de", fallback_language="en")

        def series_details(self, *args, **kwargs):
            return {"data": {
                "id": 123,
                "name": "Die Tageb\u00fccher der Apothekerin",
                "firstAired": "2023-10-22",
            }}

    result = Client()._series_suggestion_from_record(
        "The Apothecary Diaries", year, {"id": 123},
    )
    assert (result is not None) is accepted
    if accepted:
        assert result.name == "Die Tageb\u00fccher der Apothekerin"
        assert result.query_title == "The Apothecary Diaries"
