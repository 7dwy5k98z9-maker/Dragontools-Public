from __future__ import annotations

from dragontools.rules.move_rules import parse_series_match_details


def test_series_detection_removes_separator_before_episode_code():
    parsed = parse_series_match_details("Stargate Atlantis - S01E15 - 10.000 Jahre.mkv")

    assert parsed is not None
    assert parsed["series"] == "Stargate Atlantis"
    assert parsed["season"] == 1
    assert parsed["episode"] == 15


def test_series_detection_keeps_internal_hyphenated_names():
    parsed = parse_series_match_details("Spider-Man - S01E01.mkv")

    assert parsed is not None
    assert parsed["series"] == "Spider-Man"


def test_series_detection_normalizes_missing_space_after_separator():
    parsed = parse_series_match_details(
        "ReZero -Starting Life in Another World- - S04E14 - Fünf Hindernisse.mkv"
    )

    assert parsed is not None
    assert parsed["series"] == "ReZero - Starting Life in Another World"


def test_existing_series_dir_matches_tmdb_colon_and_year_suffix(tmp_path):
    from dragontools.rules.move_rules import find_existing_series_dir

    existing = tmp_path / "ReZERO - Starting Life in Another World (2016)"
    existing.mkdir()

    assert find_existing_series_dir(
        str(tmp_path),
        "Re:ZERO - Starting Life in Another World (2016)",
    ) == str(existing)


def test_series_detection_removes_release_dots_and_trailing_year_before_episode_code():
    parsed = parse_series_match_details("Iron.Wok.Jan.2026.S01E09.German.1080p.WEB.H264-GRP.mkv")

    assert parsed is not None
    assert parsed["series"] == "Iron Wok Jan"
    assert parsed["season"] == 1
    assert parsed["episode"] == 9


def test_series_detection_removes_parenthesized_year_before_episode_code():
    parsed = parse_series_match_details("Kaguya-sama Love is War (2019) - S00E05.mkv")

    assert parsed is not None
    assert parsed["series"] == "Kaguya-sama Love is War"
    assert parsed["season"] == 0
    assert parsed["episode"] == 5


def test_existing_series_dir_tolerates_optional_internal_hyphen(tmp_path):
    from dragontools.rules.move_rules import find_existing_series_dir

    base = tmp_path / "TV"
    target = base / "Special Ops - Lioness (2023)"
    target.mkdir(parents=True)

    assert find_existing_series_dir(str(base), "Special Ops Lioness") == str(target)
    assert find_existing_series_dir(str(base), "Special Ops – Lioness (2023)") == str(target)


def test_existing_series_dir_uses_year_to_disambiguate_fraction_titles(tmp_path):
    from dragontools.rules.move_rules import find_existing_series_dir, find_series_dir_candidates

    base = tmp_path / "Anime"
    older = base / "Ranma ½ (1989)"
    newer = base / "Ranma ½ (2024)"
    older.mkdir(parents=True)
    newer.mkdir(parents=True)

    assert find_series_dir_candidates(str(base), "Ranma 1/2") == [str(older), str(newer)]
    assert find_existing_series_dir(str(base), "Ranma 1/2", year=2024) == str(newer)
    assert find_existing_series_dir(str(base), "Ranma 1/2 (2024)") == str(newer)
