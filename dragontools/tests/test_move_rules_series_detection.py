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


def test_existing_series_dir_matches_case_year_and_restart_title(tmp_path):
    from dragontools.rules.move_rules import find_existing_series_dir

    base = tmp_path / "Anime"
    target = base / "MAGICAL GIRL RAISING PROJECT restart (2026)"
    target.mkdir(parents=True)

    assert find_existing_series_dir(
        str(base), "MAGICAL GIRL RAISING PROJECT RESTART"
    ) == str(target)


def test_existing_series_dir_allows_project_projekt_and_one_missing_leading_word(tmp_path):
    from dragontools.rules.move_rules import find_existing_series_dir

    base = tmp_path / "Anime"
    target = base / "MAGICAL GIRL RAISING PROJECT restart (2026)"
    target.mkdir(parents=True)

    assert find_existing_series_dir(
        str(base), "Girl Raising Projekt Restart"
    ) == str(target)


def test_existing_series_dir_fuzzy_fallback_does_not_drop_distinguishing_suffix(tmp_path):
    from dragontools.rules.move_rules import find_existing_series_dir

    base = tmp_path / "Anime"
    target = base / "MAGICAL GIRL RAISING PROJECT Restart (2026)"
    target.mkdir(parents=True)

    # "Restart" ist ein unterscheidender Suffix und darf nicht einfach
    # verschwinden; sonst koennten Originalserie und Fortsetzung zusammenfallen.
    assert find_existing_series_dir(
        str(base), "MAGICAL GIRL RAISING PROJECT"
    ) is None


def test_existing_series_dir_fuzzy_fallback_rejects_short_generic_prefix_drop(tmp_path):
    from dragontools.rules.move_rules import find_existing_series_dir

    base = tmp_path / "TV"
    target = base / "The Office (2005)"
    target.mkdir(parents=True)

    assert find_existing_series_dir(str(base), "Office") is None


def test_fuzzy_series_candidates_keep_multiple_year_editions_for_dropdown(tmp_path):
    from dragontools.rules.move_rules import find_series_dir_candidates

    base = tmp_path / "Anime"
    older = base / "MAGICAL GIRL RAISING PROJECT Restart (2016)"
    newer = base / "Girl Raising Projekt Restart (2026)"
    older.mkdir(parents=True)
    newer.mkdir(parents=True)

    # Ohne bekannte Jahresangabe muessen beide plausiblen Editionen erhalten
    # bleiben. Der MoveRouter zeigt bei >1 Kandidat das bestehende Dropdown.
    assert find_series_dir_candidates(
        str(base), "MAGICAL GIRL RAISING PROJECT RESTART"
    ) == [str(older), str(newer)]


def test_fuzzy_series_candidates_known_year_selects_only_that_edition(tmp_path):
    from dragontools.rules.move_rules import find_series_dir_candidates

    base = tmp_path / "Anime"
    older = base / "MAGICAL GIRL RAISING PROJECT Restart (2016)"
    newer = base / "Girl Raising Projekt Restart (2026)"
    older.mkdir(parents=True)
    newer.mkdir(parents=True)

    assert find_series_dir_candidates(
        str(base), "MAGICAL GIRL RAISING PROJECT RESTART", year=2026
    ) == [str(newer)]
    assert find_series_dir_candidates(
        str(base), "MAGICAL GIRL RAISING PROJECT RESTART (2016)"
    ) == [str(older)]


def test_move_router_uses_existing_dropdown_for_multiple_fuzzy_year_editions(tmp_path):
    from dragontools.core.move_routing import MoveRouter

    base = tmp_path / "Anime"
    older = base / "MAGICAL GIRL RAISING PROJECT Restart (2016)"
    newer = base / "Girl Raising Projekt Restart (2026)"
    older.mkdir(parents=True)
    newer.mkdir(parents=True)
    requests = []

    def ask(payload):
        requests.append(payload)
        assert payload["type"] == "choose_series_folder"
        assert {item["path"] for item in payload["candidates"]} == {str(older), str(newer)}
        return {"path": str(newer)}

    router = MoveRouter(
        tv_path="",
        anime_path=str(base),
        filme_path="",
        all_video_files=[],
        planned_target_for=lambda _path: None,
        ask=ask,
        log=lambda *_args: None,
    )

    target = router.find_series_dir(
        str(base), "MAGICAL GIRL RAISING PROJECT RESTART", season=1
    )

    assert requests
    assert target == str(newer / "Staffel 01")
