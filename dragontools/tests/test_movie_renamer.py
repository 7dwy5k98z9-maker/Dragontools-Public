from __future__ import annotations


def test_parse_movie_release_name_strips_release_tags_and_keeps_search_core():
    from dragontools.core.movie_renamer import parse_movie_release_name

    parsed = parse_movie_release_name(
        "Das.Gesetz.der.Rache.2009.Directors.Cut.German.DTSHD.DL."
        "2160p.UHD.BluRay.DV.HDR10Plus.HEVC.Remux-NIMA4K.mkv"
    )

    assert parsed.query_title == "Das Gesetz der Rache"
    assert parsed.year == 2009
    assert parsed.release_group == "NIMA4K"
    assert "Director's Cut" in parsed.edition_hints
    assert "HDR" in parsed.technical_tags
    assert "Video" in parsed.technical_tags


def test_build_movie_rename_proposal_prefers_matching_title_and_year(tmp_path):
    from dragontools.core.movie_renamer import build_movie_rename_proposal

    source = tmp_path / (
        "Das.Gesetz.der.Rache.2009.Directors.Cut.German.DTSHD.DL."
        "2160p.UHD.BluRay.DV.HDR10Plus.HEVC.Remux-NIMA4K.mkv"
    )
    source.write_text("video", encoding="utf-8")

    def resolver(title: str, year: int | None):
        assert title == "Das Gesetz der Rache"
        assert year == 2009
        return [
            {"id": 10, "title": "Ein anderer Film", "release_date": "2009-01-01"},
            {"id": 20, "title": "Das Gesetz der Rache", "release_date": "2009-10-15"},
        ]

    proposal = build_movie_rename_proposal(source, resolver=resolver)

    assert proposal.status == "ok"
    assert proposal.target_name == "Das Gesetz der Rache (2009).mkv"
    assert proposal.can_auto_accept is True
    assert proposal.selected is not None
    assert proposal.selected.tmdb_id == 20
    assert len(proposal.candidates) == 2


def test_build_movie_rename_proposal_retries_german_umlaut_variant(tmp_path):
    from dragontools.core.movie_renamer import build_movie_rename_proposal

    source = tmp_path / "Der.Kinderfluesterer.2026.GERMAN.1080p.WEB.H264-GRP.mkv"
    source.write_text("video", encoding="utf-8")
    calls: list[str] = []

    def resolver(title: str, year: int | None):
        calls.append(title)
        assert year == 2026
        if title == "Der Kinderflüsterer":
            return [
                {
                    "id": 44,
                    "title": "Der Kinderflüsterer",
                    "release_date": "2026-02-01",
                }
            ]
        return []

    proposal = build_movie_rename_proposal(source, resolver=resolver)

    assert calls == ["Der Kinderfluesterer", "Der Kinderflüsterer"]
    assert proposal.status == "ok"
    assert proposal.target_name == "Der Kinderflüsterer (2026).mkv"
    assert proposal.selected is not None
    assert proposal.selected.score == 1.0


def test_movie_rename_proposal_skips_probable_series_episode(tmp_path):
    from dragontools.core.movie_renamer import build_movie_rename_proposal

    source = tmp_path / "Stargate.Atlantis.S01E15.10000.Jahre.German.1080p.mkv"
    source.write_text("video", encoding="utf-8")
    called = False

    def resolver(_title: str, _year: int | None):
        nonlocal called
        called = True
        return []

    proposal = build_movie_rename_proposal(source, resolver=resolver)

    assert proposal.status == "not_movie"
    assert called is False
    assert proposal.parsed.is_probable_series is True


def test_build_series_rename_proposal_uses_episode_metadata_without_trailing_dash(tmp_path):
    from dragontools.core.movie_renamer import build_series_rename_proposal

    source = tmp_path / "Stargate Atlantis - S01E15 - 10.000 Jahre.mkv"
    source.write_text("video", encoding="utf-8")

    def resolver(series: str, season: int, episode: int, year: int | None):
        assert series == "Stargate Atlantis"
        assert season == 1
        assert episode == 15
        return [
            {
                "series": "Stargate Atlantis",
                "season": 1,
                "episode": 15,
                "episode_title": "10.000 Jahre",
                "provider": "thetvdb",
                "provider_id": 100,
                "episode_id": 5001,
            }
        ]

    proposal = build_series_rename_proposal(source, resolver=resolver)

    assert proposal.status == "ok"
    assert proposal.target_name == "Stargate Atlantis - S01E15 - 10.000 Jahre.mkv"
    assert proposal.selected is not None
    assert proposal.selected.provider == "thetvdb"


def test_parse_series_release_name_preserves_episode_number_dot():
    from dragontools.core.movie_renamer import parse_series_release_name

    parsed = parse_series_release_name("Stargate Atlantis - S01E15 - 10.000 Jahre.mkv")

    assert parsed is not None
    assert parsed.series == "Stargate Atlantis"
    assert parsed.season == 1
    assert parsed.episode == 15
    assert parsed.episode_title == "10.000 Jahre"


def test_parse_series_release_name_removes_release_dots_and_year_from_series():
    from dragontools.core.movie_renamer import parse_series_release_name

    parsed = parse_series_release_name("Iron.Wok.Jan.2026.S01E09.German.1080p.WEB.H264-GRP.mkv")

    assert parsed is not None
    assert parsed.series == "Iron Wok Jan"
    assert parsed.year == 2026
    assert parsed.season == 1
    assert parsed.episode == 9


def test_build_movie_rename_proposal_marks_conflict(tmp_path):
    from dragontools.core.movie_renamer import build_movie_rename_proposal

    source = tmp_path / "Ready.or.Not.2019.German.1080p.WEB.H264.mkv"
    target = tmp_path / "Ready or Not (2019).mkv"
    source.write_text("source", encoding="utf-8")
    target.write_text("target", encoding="utf-8")

    proposal = build_movie_rename_proposal(
        source,
        resolver=lambda _title, _year: [{"id": 7, "title": "Ready or Not", "release_date": "2019-08-21"}],
    )

    assert proposal.status == "conflict"
    assert proposal.target_exists is True
    assert "Zieldatei existiert bereits." in proposal.warnings


def test_target_filename_sanitizes_windows_characters():
    from dragontools.core.movie_renamer import build_target_filename

    assert build_target_filename('Film: Test/Name?', 2024, ".mkv") == "Film Test-Name (2024).mkv"


def test_series_target_filename_uses_standard_pattern_and_special_replacements():
    from dragontools.core.movie_renamer import build_series_target_filename

    target = build_series_target_filename(
        'Serie: Name/Staffel|Test*',
        4,
        14,
        'Fünf Hindernisse? #1 <Finale>',
        ".mkv",
    )

    assert target == "Serie Name-Staffel.TestX - S04E14 - Fünf Hindernisse 1 Finale.mkv"


def test_series_target_filename_preserves_official_trailing_period_in_series_title():
    from dragontools.core.movie_renamer import build_series_target_filename

    target = build_series_target_filename(
        "Magilumiere Inc.",
        2,
        7,
        "Das ist doch eindeutig Game Over",
        ".mkv",
    )

    assert target == "Magilumiere Inc. - S02E07 - Das ist doch eindeutig Game Over.mkv"


def test_movie_rename_candidate_keeps_provider_for_dropdown(tmp_path):
    from dragontools.core.movie_renamer import build_movie_rename_proposal

    source = tmp_path / "Test.Film.2024.mkv"
    source.write_text("video", encoding="utf-8")

    proposal = build_movie_rename_proposal(
        source,
        resolver=lambda _title, _year: [
            {"id": 12, "title": "Test Film", "release_date": "2024-01-01", "provider": "tmdb"},
            {"id": 222, "title": "Test Film", "year": "2024", "provider": "thetvdb", "provider_id": 222},
        ],
    )

    labels = [candidate.choice_label for candidate in proposal.candidates]

    assert any("TMDB" in label for label in labels)
    assert any("TheTVDB" in label for label in labels)


def test_rename_movie_file_keeps_folder_and_changes_only_file_name(tmp_path):
    from dragontools.core.movie_renamer import rename_movie_file

    source = tmp_path / "Alter.Name.2020.German.mkv"
    source.write_text("video", encoding="utf-8")

    target = rename_movie_file(source, "Neuer Name (2020).mkv")

    assert target == tmp_path / "Neuer Name (2020).mkv"
    assert target.exists()
    assert not source.exists()


def test_series_metadata_candidates_honor_preferred_provider_before_score(tmp_path):
    from dragontools.core.movie_renamer import build_series_rename_proposal

    source = tmp_path / "Jaadugar A Witch in Mongolia - S01E03.mkv"
    source.write_text("video", encoding="utf-8")

    class FakeClient:
        provider_order = ("thetvdb", "tmdb")

        def resolve_episode_candidates(self, _path, *, limit=6):
            return (
                {
                    "series": "Jaadugar A Witch in Mongolia",
                    "season": 1,
                    "episode": 3,
                    "episode_title": "TMDB Titel",
                    "provider": "tmdb",
                    "provider_id": 1,
                },
                {
                    # Absichtlich etwas schlechterer Text-Match: die explizite
                    # Provider-Priorität soll trotzdem zuerst gelten.
                    "series": "Jaadugar - A Witch in Mongolia",
                    "season": 1,
                    "episode": 3,
                    "episode_title": "TVDB Titel",
                    "provider": "thetvdb",
                    "provider_id": 2,
                },
            )

    proposal = build_series_rename_proposal(source, client=FakeClient())

    assert proposal.selected is not None
    assert proposal.selected.provider == "thetvdb"
    assert [candidate.provider for candidate in proposal.candidates[:2]] == ["thetvdb", "tmdb"]


def test_explicit_series_alias_is_selected_before_unaliased_exact_match(tmp_path, monkeypatch):
    import dragontools.core.movie_renamer as movie_renamer

    source = tmp_path / "Lioness (2023) - S01E01.mkv"
    source.write_text("video", encoding="utf-8")
    monkeypatch.setattr(
        movie_renamer,
        "apply_title_exception",
        lambda value: "Special Ops Lioness" if value == "Lioness" else value,
    )

    class FakeClient:
        provider_order = ("tmdb",)

        def resolve_episode_candidates(self, _path, *, limit=6):
            return (
                {
                    "series": "Lioness",
                    "season": 1,
                    "episode": 1,
                    "episode_title": "Falsche Serie",
                    "provider": "tmdb",
                    "provider_id": 1,
                    "episode_id": 11,
                },
                {
                    "series": "Special Ops Lioness",
                    "season": 1,
                    "episode": 1,
                    "episode_title": "Geopferte Kaempfer",
                    "provider": "tmdb",
                    "provider_id": 2,
                    "episode_id": 22,
                },
            )

    proposal = movie_renamer.build_series_rename_proposal(source, client=FakeClient())

    assert proposal.selected is not None
    assert proposal.selected.series == "Special Ops Lioness"
    assert proposal.selected.match_reason == "Aliasregel"
    assert [candidate.series for candidate in proposal.candidates[:2]] == [
        "Special Ops Lioness",
        "Lioness",
    ]


def test_series_missing_provider_episode_title_uses_folge_fallback_and_not_100_percent(tmp_path):
    from dragontools.core.movie_renamer import build_series_rename_proposal

    source = tmp_path / "american.dad.s22e10.german.dl.1080p.web.h264-wayne.mkv"
    source.write_text("video", encoding="utf-8")

    proposal = build_series_rename_proposal(
        source,
        resolver=lambda *_args: [
            {
                "series": "American Dad!",
                "season": 22,
                "episode": 10,
                "episode_title": "",
                "provider": "tmdb",
                "provider_id": 1433,
                "episode_id": 999999,
            }
        ],
    )

    assert proposal.selected is not None
    assert proposal.selected.episode_title == "Folge 10"
    assert proposal.target_name == "American Dad! - S22E10 - Folge 10.mkv"
    assert proposal.confidence < 1.0
    assert "american.dad.s22e10" not in proposal.target_name.lower()


def test_series_without_episode_metadata_uses_provider_series_and_folge_fallback(tmp_path):
    from dragontools.core.movie_renamer import build_series_rename_proposal
    from dragontools.core.online_metadata import SeriesMetadataSuggestion

    source = tmp_path / "american.dad.s22e10.german.dl.1080p.web.h264-wayne.mkv"
    source.write_text("video", encoding="utf-8")

    class FakeClient:
        def resolve_episode_candidates(self, _path, *, limit=6):
            return ()

        def resolve_episode_file(self, _path):
            return None

        def resolve_series(self, _series, *, year=None):
            return SeriesMetadataSuggestion(
                query_title="american dad",
                query_year=year,
                tmdb_id=1433,
                name="American Dad!",
                original_name="American Dad!",
                first_air_year=2005,
                provider="tmdb",
                provider_id=1433,
            )

    proposal = build_series_rename_proposal(source, client=FakeClient())

    assert proposal.selected is not None
    assert proposal.selected.series == "American Dad!"
    assert proposal.selected.episode_title == "Folge 10"
    assert proposal.target_name == "American Dad! - S22E10 - Folge 10.mkv"
    assert proposal.confidence < 1.0


def test_series_no_metadata_result_never_reuses_release_filename_as_episode_title(tmp_path):
    from dragontools.core.movie_renamer import build_series_rename_proposal

    source = tmp_path / "american.dad.s22e10.german.dl.1080p.web.h264-wayne.mkv"
    source.write_text("video", encoding="utf-8")

    proposal = build_series_rename_proposal(source, resolver=lambda *_args: [])

    assert proposal.status == "no_match"
    assert proposal.target_name == "american dad - S22E10 - Folge 10.mkv"
    assert "german" not in proposal.target_name.lower()
    assert "wayne" not in proposal.target_name.lower()


def test_series_generic_provider_episode_title_is_normalized_and_confidence_capped(tmp_path):
    from dragontools.core.movie_renamer import build_series_rename_proposal

    source = tmp_path / "American.Dad.S22E10.German.1080p.WEB.H264.mkv"
    source.write_text("video", encoding="utf-8")

    proposal = build_series_rename_proposal(
        source,
        resolver=lambda *_args: [
            {
                "series": "American Dad!",
                "season": 22,
                "episode": 10,
                "episode_title": "Episode 10",
                "provider": "tmdb",
                "provider_id": 1433,
                "episode_id": 1234,
            }
        ],
    )

    assert proposal.target_name == "American Dad! - S22E10 - Folge 10.mkv"
    assert proposal.selected is not None
    assert proposal.selected.match_reason == "Episodentitel offen"
    assert proposal.confidence == 0.92
