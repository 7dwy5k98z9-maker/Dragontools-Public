from __future__ import annotations

from pathlib import Path

import pytest

from dragontools.core.movie_renamer import (
    build_series_rename_proposal,
    parse_movie_release_name,
    parse_series_release_name,
)
from dragontools.core.online_metadata_common import parse_series_query
from dragontools.rules import renamer_rules
from dragontools.rules.move_series_detection import parse_series_match_details


@pytest.fixture
def release_groups(monkeypatch):
    rules = renamer_rules.migrate_renamer_rules({"release_groups": ["STARS", "NIMA4K"]})
    monkeypatch.setattr(renamer_rules, "_RULES_CACHE", rules)
    return rules


def test_release_group_prefix_is_removed_from_series_search(release_groups):
    parsed = parse_series_release_name("STARS.The.Show.S01E03.German.1080p.WEB.mkv")
    assert parsed is not None
    assert parsed.series == "The Show"
    assert parsed.release_group == "STARS"
    assert parsed.season == 1
    assert parsed.episode == 3


def test_release_group_prefix_is_removed_from_movie_search(release_groups):
    parsed = parse_movie_release_name("STARS.The.Movie.2026.German.1080p.WEB.mkv")
    assert parsed.query_title == "The Movie"
    assert parsed.year == 2026
    assert parsed.release_group == "STARS"


def test_release_group_filter_only_touches_name_edges(release_groups):
    parsed = parse_series_release_name("A.STARS.Story.S01E01.mkv")
    assert parsed is not None
    assert parsed.series == "A STARS Story"
    assert parsed.release_group == ""


def test_release_group_suffix_from_config_is_removed(release_groups):
    parsed = parse_series_release_name("The.Show.S01E01-STARS.mkv")
    assert parsed is not None
    assert parsed.series == "The Show"
    assert parsed.release_group == "STARS"


def test_multiple_configured_release_group_prefixes_are_removed(release_groups):
    parsed = parse_series_release_name("NIMA4K-STARS.The.Show.S01E01.mkv")
    assert parsed is not None
    assert parsed.series == "The Show"
    assert parsed.release_group == "NIMA4K, STARS"


def test_reversed_episode_season_pattern_e05s06_is_supported(release_groups):
    parsed = parse_series_release_name("STARS.The.Show.E05S06.1080p.WEB.mkv")
    assert parsed is not None
    assert parsed.series == "The Show"
    assert parsed.episode == 5
    assert parsed.season == 6
    assert parsed.season_missing is False


def test_reversed_episode_season_pattern_with_separators_is_supported():
    parsed = parse_series_match_details("The Show - E05 S06 - Titel.mkv")
    assert parsed is not None
    assert parsed["series"] == "The Show"
    assert parsed["episode"] == 5
    assert parsed["season"] == 6


def test_ep01_is_classified_as_series_but_requires_season(release_groups):
    movie = parse_movie_release_name("STARS.The.Show.EP01.mkv")
    parsed = parse_series_release_name("STARS.The.Show.EP01.mkv")
    assert movie.is_probable_series is True
    assert parsed is not None
    assert parsed.series == "The Show"
    assert parsed.episode == 1
    assert parsed.season == 0
    assert parsed.season_missing is True
    assert any("Staffel fehlt" in warning for warning in parsed.warnings)


def test_ep01_without_override_does_not_call_provider(tmp_path: Path, release_groups):
    source = tmp_path / "STARS.The.Show.EP01.mkv"
    source.write_bytes(b"x")
    called = False

    def resolver(*_args):
        nonlocal called
        called = True
        return []

    proposal = build_series_rename_proposal(source, resolver=resolver)
    assert proposal.status == "needs_season"
    assert proposal.parsed.season_missing is True
    assert called is False


def test_ep01_with_season_override_uses_selected_season(tmp_path: Path, release_groups):
    source = tmp_path / "STARS.The.Show.EP01.mkv"
    source.write_bytes(b"x")
    seen = {}

    def resolver(series: str, season: int, episode: int, year: int | None):
        seen.update(series=series, season=season, episode=episode, year=year)
        return [{
            "series": "The Show",
            "season": season,
            "episode": episode,
            "episode_title": "Pilot",
            "provider": "test",
            "provider_id": 1,
            "episode_id": 10,
        }]

    proposal = build_series_rename_proposal(source, resolver=resolver, season_override=4)
    assert seen == {"series": "The Show", "season": 4, "episode": 1, "year": None}
    assert proposal.parsed.season == 4
    assert proposal.parsed.season_missing is False
    assert proposal.target_name == "The Show - S04E01 - Pilot.mkv"


def test_parse_series_query_strips_ep_and_reversed_markers(release_groups):
    assert parse_series_query("STARS.The.Show.EP01.mkv").title == "The Show"
    assert parse_series_query("STARS.The.Show.E05S06.mkv").title == "The Show"


def test_rule_migration_deduplicates_release_groups_case_insensitively():
    migrated = renamer_rules.migrate_renamer_rules({
        "_schema_version": 2,
        "release_groups": ["STARS", "stars", {"name": "NIMA4K"}, ""],
    })
    assert migrated["_schema_version"] == 3
    assert migrated["release_groups"] == ["STARS", "NIMA4K"]
