from __future__ import annotations


def test_movie_nfo_contains_clean_tmdb_metadata_without_user_state(tmp_path):
    from dragontools.core.jellyfin_nfo import write_movie_nfo
    from dragontools.core.online_metadata import MovieMetadataSuggestion

    suggestion = MovieMetadataSuggestion(
        query_title="Alarmstufe Rot 2",
        query_year=1995,
        tmdb_id=3512,
        title="Alarmstufe Rot 2",
        original_title="Under Siege 2: Dark Territory",
        release_year=1995,
        overview="Ein Ex-Navy-Seal verhindert eine Zugentführung.",
        release_date="1995-07-13",
        runtime_min=100,
        vote_average=6.0,
        imdb_id="tt0114781",
        genres=("Action", "Thriller"),
        studios=("Warner Bros.",),
        directors=("Geoff Murphy",),
        actors=({"name": "Steven Seagal", "role": "Casey Ryback", "sortorder": 0},),
        collection_id=123,
        collection_name="Alarmstufe Rot",
        collection_part_count=2,
    )

    nfo = write_movie_nfo(tmp_path / "Alarmstufe Rot 2.nfo", suggestion, include_fileinfo=False)
    text = nfo.read_text(encoding="utf-8")

    assert "<movie>" in text
    assert "<title>Alarmstufe Rot 2</title>" in text
    assert "<tmdbid>3512</tmdbid>" in text
    assert "<imdbid>tt0114781</imdbid>" in text
    assert "<set>" in text
    assert "<name>Alarmstufe Rot</name>" in text
    assert "lastplayed" not in text
    assert "resume" not in text
    assert "/config/metadata" not in text


def test_episode_nfo_uses_episode_root_and_numbers(tmp_path):
    from dragontools.core.jellyfin_nfo import write_episode_nfo
    from dragontools.core.online_metadata import EpisodeMetadataSuggestion

    suggestion = EpisodeMetadataSuggestion(
        query_series="Stargate Atlantis",
        series_tmdb_id=2290,
        episode_tmdb_id=1001,
        show_name="Stargate Atlantis",
        original_show_name="Stargate Atlantis",
        season_number=1,
        episode_number=15,
        title="10.000 Jahre",
        overview="Die Crew findet eine alte Stadt.",
    )

    nfo = write_episode_nfo(tmp_path / "Stargate Atlantis - S01E15 - 10.000 Jahre.nfo", suggestion, include_fileinfo=False)
    text = nfo.read_text(encoding="utf-8")

    assert "<episodedetails>" in text
    assert "<showtitle>Stargate Atlantis</showtitle>" in text
    assert "<season>1</season>" in text
    assert "<episode>15</episode>" in text


def test_episode_nfo_writes_tvdb_ids_for_thetvdb_provider(tmp_path):
    from dragontools.core.jellyfin_nfo import write_episode_nfo
    from dragontools.core.online_metadata import EpisodeMetadataSuggestion

    suggestion = EpisodeMetadataSuggestion(
        query_series="Stargate Atlantis",
        series_tmdb_id=2290,
        episode_tmdb_id=5001,
        show_name="Stargate Atlantis",
        original_show_name="Stargate Atlantis",
        season_number=1,
        episode_number=15,
        title="10.000 Jahre",
        provider="thetvdb",
        series_provider_id=100,
        episode_provider_id=5001,
    )

    nfo = write_episode_nfo(tmp_path / "episode.nfo", suggestion, include_fileinfo=False)
    text = nfo.read_text(encoding="utf-8")

    assert "<tvdbid>5001</tvdbid>" in text
    assert '<uniqueid type="tvdb" default="true">5001</uniqueid>' in text
    assert "<tmdbid>" not in text
