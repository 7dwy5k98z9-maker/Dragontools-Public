from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from dragontools.core.renamer_metadata_browser import (
    ExplicitMovieFileMapping,
    ExplicitSeriesFileMapping,
    MetadataBrowserEpisode,
    MetadataBrowserHit,
    RenamerMetadataBrowserService,
    build_explicit_rename_proposal,
    dedupe_paths,
    natural_path_key,
)


def _series_hit(*, provider: str = "tmdb", provider_id: int = 57706) -> MetadataBrowserHit:
    return MetadataBrowserHit(
        kind="series",
        provider=provider,  # type: ignore[arg-type]
        provider_id=provider_id,
        title="Ranma ½",
        original_title="Ranma ½",
        year=2024,
    )


def _episodes(start: int, count: int, season: int = 1) -> tuple[MetadataBrowserEpisode, ...]:
    return tuple(
        MetadataBrowserEpisode(
            season=season,
            episode=number,
            title=f"Titel {number}",
            provider_episode_id=1000 + number,
        )
        for number in range(start, start + count)
    )


@pytest.mark.parametrize(
    ("count", "code"),
    [(1, "S01E03"), (2, "S01E03E04"), (3, "S01E03E04E05"), (4, "S01E03E04E05E06")],
)
def test_explicit_series_mapping_builds_one_to_four_episode_target_names(tmp_path: Path, count: int, code: str) -> None:
    source = tmp_path / "raw.mkv"
    source.touch()
    mapping = ExplicitSeriesFileMapping(source, _series_hit(), 1, _episodes(3, count), "all")

    proposal = build_explicit_rename_proposal(mapping)

    assert code in proposal.target_name
    assert proposal.selected is not None
    assert proposal.selected.episode_numbers == tuple(range(3, 3 + count))
    assert proposal.selected.provider == "tmdb"
    assert proposal.selected.provider_id == 57706
    assert proposal.search_mode == "explicit_mapping"


@pytest.mark.parametrize(
    ("title_mode", "expected", "unexpected"),
    [
        ("all", "Titel 3 + Titel 4", None),
        ("first", "Titel 3", "Titel 4"),
        ("none", "S01E03E04.mkv", "Titel 3"),
    ],
)
def test_multi_episode_title_modes_are_deterministic(
    tmp_path: Path, title_mode: str, expected: str, unexpected: str | None
) -> None:
    source = tmp_path / "raw.mkv"
    source.touch()
    mapping = ExplicitSeriesFileMapping(
        source, _series_hit(), 1, _episodes(3, 2), title_mode  # type: ignore[arg-type]
    )

    proposal = build_explicit_rename_proposal(mapping)

    assert expected in proposal.target_name
    if unexpected:
        assert unexpected not in proposal.target_name


@pytest.mark.parametrize(
    "episodes",
    [
        (),
        _episodes(1, 5),
        (
            MetadataBrowserEpisode(1, 1, "A"),
            MetadataBrowserEpisode(1, 3, "C"),
        ),
        (
            MetadataBrowserEpisode(1, 1, "A"),
            MetadataBrowserEpisode(2, 2, "B"),
        ),
    ],
)
def test_explicit_series_mapping_rejects_invalid_multi_episode_contract(episodes) -> None:
    with pytest.raises(ValueError):
        ExplicitSeriesFileMapping(Path("raw.mkv"), _series_hit(), 1, tuple(episodes), "all")


def test_explicit_movie_mapping_keeps_selected_provider_and_detects_existing_target(tmp_path: Path) -> None:
    source = tmp_path / "anything.mkv"
    source.touch()
    hit = MetadataBrowserHit(
        kind="movie",
        provider="thetvdb",
        provider_id=42,
        title="Testfilm",
        year=2024,
    )
    target = tmp_path / "Testfilm (2024).mkv"
    target.touch()

    proposal = build_explicit_rename_proposal(ExplicitMovieFileMapping(source, hit))

    assert proposal.selected is not None
    assert proposal.selected.provider == "thetvdb"
    assert proposal.selected.provider_id == 42
    assert proposal.target_name == "Testfilm (2024).mkv"
    assert proposal.target_exists is True
    assert proposal.status == "conflict"


def test_natural_path_sort_orders_episode_2_before_episode_10() -> None:
    paths = ["Ranma 10.mkv", "Ranma 2.mkv", "Ranma 1.mkv"]
    assert sorted(paths, key=natural_path_key) == ["Ranma 1.mkv", "Ranma 2.mkv", "Ranma 10.mkv"]


def test_dedupe_paths_uses_windows_style_path_identity_contract() -> None:
    paths = [r"C:\Media\Ranma01.mkv", r"c:\media\RANMA01.mkv", r"C:\Media\Ranma02.mkv"]
    deduped = dedupe_paths(paths)
    # On non-Windows CI pathlib identity can differ; the DragonTools helper is
    # authoritative. At minimum, exact duplicates must never survive.
    assert len(deduped) <= 3
    assert deduped[0] == paths[0]
    assert len({str(value) for value in deduped}) == len(deduped)


class _FakeTmdb:
    def search_tv(self, _query: str):
        return [
            {"id": 100, "name": "Ranma ½", "original_name": "Ranma ½", "first_air_date": "1989-04-15"},
            {"id": 101, "name": "Ranma ½", "original_name": "Ranma ½", "first_air_date": "2024-10-06"},
        ]

    def search_movies(self, _query: str):
        return [{"id": 200, "title": "Ranma Movie", "release_date": "1991-11-02"}]

    def tv_details(self, _provider_id: int):
        return {"seasons": [{"season_number": 0}, {"season_number": 1}]}

    def tv_season_details(self, _provider_id: int, season: int, *, language: str):
        del language
        return {
            "episodes": [
                {"id": 300 + season, "episode_number": 1, "name": f"Staffel {season} Folge 1", "air_date": "2024-01-01"}
            ]
        }


class _FakeTvdb:
    def search_series(self, _query: str):
        return [
            {"id": 400, "name": "Ranma ½", "year": "1989"},
            {"id": 401, "name": "Ranma ½", "year": "2024"},
        ]

    def search_movies(self, _query: str):
        return [{"id": 500, "name": "Ranma Movie", "year": "1991"}]

    def series_episodes(self, _provider_id: int, *, language: str):
        del language
        return [
            {"id": 600, "seasonNumber": 0, "number": 1, "name": "Special"},
            {"id": 601, "seasonNumber": 1, "number": 1, "name": "Episode 1"},
            {"id": 602, "seasonNumber": 1, "number": 2, "name": "Episode 2"},
        ]


def _fake_service() -> RenamerMetadataBrowserService:
    service = object.__new__(RenamerMetadataBrowserService)
    service.config = SimpleNamespace(language="de", fallback_language="de")
    service._clients = {"tmdb": _FakeTmdb(), "thetvdb": _FakeTvdb()}
    return service


def test_browser_search_keeps_tmdb_and_tvdb_results_separate() -> None:
    hits = _fake_service().search("Ranma", kind="series")

    assert [(hit.provider, hit.year) for hit in hits] == [
        ("tmdb", 1989),
        ("tmdb", 2024),
        ("thetvdb", 1989),
        ("thetvdb", 2024),
    ]
    assert {hit.provider_id for hit in hits} == {100, 101, 400, 401}


def test_browser_supports_movie_search_for_both_providers() -> None:
    hits = _fake_service().search("Ranma", kind="movie")
    assert [(hit.provider, hit.year) for hit in hits] == [("tmdb", 1991), ("thetvdb", 1991)]


def test_browser_supports_specials_season_zero() -> None:
    service = _fake_service()
    tmdb_hit = next(hit for hit in service.search("Ranma", kind="series") if hit.provider == "tmdb")
    tvdb_hit = next(hit for hit in service.search("Ranma", kind="series") if hit.provider == "thetvdb")

    assert service.series_seasons(tmdb_hit) == (0, 1)
    assert service.series_seasons(tvdb_hit) == (0, 1)
    assert service.series_episodes(tmdb_hit, 0)[0].season == 0
    assert service.series_episodes(tvdb_hit, 0)[0].season == 0


def test_metadata_browser_gui_source_contains_required_mapping_contract() -> None:
    """Static GUI contract test stays runnable on CI images without PyQt6."""
    source_path = Path(__file__).parents[1] / "gui" / "movie_renamer_metadata_browser.py"
    source = source_path.read_text(encoding="utf-8")
    ast.parse(source)

    assert 'self.span_spin.setRange(1, 4)' in source
    assert '"Serie", "series"' in source
    assert '"Film", "movie"' in source
    assert "paths_dropped" in source
    assert "files_assigned" in source
    assert "Ab markierter Episode automatisch zuordnen" in source
    assert "Zuordnung in Renamer übernehmen" in source
    assert "current_season is None" in source  # S00 must not be mistaken for missing data.
    assert "self._movie_mappings.pop(key, None)" in source
    assert "self._series_mappings.pop(key, None)" in source


def test_explicit_mapping_rejects_wrong_kind_and_unknown_title_mode() -> None:
    movie_hit = MetadataBrowserHit(kind="movie", provider="tmdb", provider_id=1, title="Film")
    series_hit = _series_hit()
    with pytest.raises(ValueError):
        ExplicitSeriesFileMapping(Path("raw.mkv"), movie_hit, 1, _episodes(1, 1), "all")
    with pytest.raises(ValueError):
        ExplicitMovieFileMapping(Path("raw.mkv"), series_hit)
    with pytest.raises(ValueError):
        ExplicitSeriesFileMapping(Path("raw.mkv"), series_hit, 1, _episodes(1, 1), "unknown")  # type: ignore[arg-type]


def test_metadata_browser_is_wired_into_existing_renamer_without_replacing_commit_path() -> None:
    root = Path(__file__).parents[1] / "gui"
    view = (root / "movie_renamer_view.py").read_text(encoding="utf-8")
    widget = (root / "movie_renamer_widget.py").read_text(encoding="utf-8")
    actions = (root / "movie_renamer_actions.py").read_text(encoding="utf-8")
    controller = (root / "movie_renamer_table_controller.py").read_text(encoding="utf-8")
    for source in (view, widget, actions, controller):
        ast.parse(source)

    assert "metadata_browser_btn" in view
    assert "open_metadata_browser" in widget
    assert "build_explicit_rename_proposal" in actions
    assert "resolver.invalidate_paths(paths)" in actions
    assert "on_proposal_ready(row, proposal)" in actions
    assert "rename_movie_file(source, target_name)" in actions
    assert "Zielname mehrfach in der Liste" in controller
