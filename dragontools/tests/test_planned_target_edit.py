from dragontools.core.planned_target_edit import (
    infer_series_season,
    rebase_series_target,
    series_root_from_target,
    target_kind,
)


def test_rebase_series_target_preserves_season_for_standard_name():
    old = r"D:\\TV\\Ranma 1989\\Staffel 06"
    result = rebase_series_target(
        r"C:\\Input\\Ranma 1989 - E05S06 - Titel.mkv",
        old,
        r"D:\\TV\\Ranma 2024",
    )
    assert result.replace("/", "\\").endswith(r"Ranma 2024\Staffel 06")


def test_ep_only_series_uses_existing_preflight_season():
    path = r"C:\\Input\\Serie EP01.mkv"
    target = r"D:\\TV\\Serie\\Staffel 04"
    assert infer_series_season(path, target) == 4
    assert target_kind(path, target) == "series"
    result = rebase_series_target(path, target, r"D:\\TV\\Serie Neu")
    assert result.replace("/", "\\").endswith(r"Serie Neu\Staffel 04")


def test_specials_remain_specials_when_rebased():
    result = rebase_series_target(
        r"C:\\Input\\Serie EP01.mkv",
        r"D:\\TV\\Serie\\Specials",
        r"D:\\TV\\Serie Neu",
    )
    assert result.replace("/", "\\").endswith(r"Serie Neu\Specials")


def test_film_target_is_not_classified_as_series():
    assert target_kind(
        r"C:\\Input\\Film (2024).mkv",
        r"D:\\Filme\\F\\Film (2024)",
    ) == "film"


def test_series_root_from_target_strips_only_season_folder():
    root = series_root_from_target(r"D:\\TV\\Ranma 2024\\Staffel 02")
    assert root.replace("/", "\\").endswith(r"TV\Ranma 2024")
