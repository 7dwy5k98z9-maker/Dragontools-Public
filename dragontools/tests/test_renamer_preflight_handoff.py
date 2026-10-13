"""Regression coverage for reuse of confirmed series identities and NAS lookup."""
from pathlib import Path

from dragontools.core.movie_renamer_models import (
    ParsedSeriesReleaseName, SeriesRenameCandidate, SeriesRenameProposal,
)
from dragontools.core.renamer_metadata_handoff import RenamerMetadataHandoff
from dragontools.gui.preflight_metadata_common import MetadataLookupCache
from dragontools.gui.preflight_metadata_series import resolve_series_metadata


def proposal(path, year=2021, provider="thetvdb", provider_id=123):
    parsed = ParsedSeriesReleaseName(Path(path).name, ".mkv", "Superman & Lois", 1, 1)
    candidate = SeriesRenameCandidate("Superman & Lois", 1, 1, year=year,
                                      provider=provider, provider_id=provider_id)
    return SeriesRenameProposal(Path(path), parsed, selected=candidate)


def fail_online(*_args, **_kwargs):
    raise AssertionError("Renamer identity must avoid another provider search")


def resolve(info, *, folders=None, database=None, online=True):
    return resolve_series_metadata(
        info, settings=None, online_enabled=online, cache=MetadataLookupCache(),
        find_series_dir_from_settings=database or (lambda *_a, **_kw: None),
        find_series_dir_candidates=folders or (lambda *_a, **_kw: []),
        suggest_series_metadata_for_name=fail_online,
    )


def test_confirmed_identity_avoids_online_lookup_with_or_without_api_settings():
    path = r"D:\Downloads\Superman & Lois - S01E01.mkv"
    cache = RenamerMetadataHandoff()
    cache.remember(path, proposal(path))
    known = cache.series_for_paths([path], "Superman & Lois")
    assert known.provider_id == 123 and known.first_air_year == 2021
    info = {"base": "D:/TV", "series_name": "Superman & Lois", "known_series": known}
    assert resolve(info) == known
    assert resolve(info, online=False) == known


def test_known_identity_disambiguates_edition_without_online_request(tmp_path):
    path = "Superman & Lois - S01E01.mkv"
    cache = RenamerMetadataHandoff()
    cache.remember(path, proposal(path))
    old, new = str(tmp_path / "Superman & Lois (1990)"), str(tmp_path / "Superman & Lois (2021)")
    result = resolve(
        {"base": str(tmp_path), "series_name": "Superman & Lois",
         "known_series": cache.series_for_paths([path], "Superman & Lois")},
        folders=lambda _base, _name, year=None: [old, new] if year is None else [new],
    )
    assert result["__existing_series_dir__"] == new


def test_unyearred_existing_folder_retains_priority_over_new_metadata_folder(tmp_path):
    path = "Superman & Lois - S01E01.mkv"
    cache = RenamerMetadataHandoff()
    cache.remember(path, proposal(path))
    existing = str(tmp_path / "Superman & Lois")
    result = resolve(
        {"base": str(tmp_path), "series_name": "Superman & Lois",
         "known_series": cache.series_for_paths([path], "Superman & Lois")},
        folders=lambda *_a, **_kw: [existing],
    )
    assert result["__existing_series_dir__"] == existing


def test_handoff_does_not_guess_missing_or_conflicting_group_identities():
    first = "Superman & Lois - S01E01.mkv"
    second = "Superman & Lois - S01E02.mkv"
    cache = RenamerMetadataHandoff()
    cache.remember(first, proposal(first))
    assert cache.series_for_paths([first, second], "Superman & Lois") is None
    cache.remember(second, proposal(second, provider="tmdb", provider_id=987))
    assert cache.series_for_paths([first, second], "Superman & Lois") is None
    assert cache.series_for_paths([first], "Other Show") is None
    assert cache.series_for_paths([first], "Superman & Lois", 1990) is None


def test_manual_target_change_is_not_treated_as_confirmed_metadata():
    path = "Other Show - S01E01.mkv"
    cache = RenamerMetadataHandoff()
    cache.remember(path, proposal(path))
    assert cache.series_for_paths([path], "Other Show") is None
    wrong_year = "Superman & Lois (1990) - S01E01.mkv"
    cache.remember(wrong_year, proposal(wrong_year))
    assert cache.series_for_paths([wrong_year], "Superman & Lois") is None


def test_handoff_is_bounded_and_unconfirmed_reuse_discards_old_identity():
    first, second = "Superman & Lois - S01E01.mkv", "Superman & Lois - S01E02.mkv"
    cache = RenamerMetadataHandoff(max_entries=1)
    cache.remember(first, proposal(first))
    cache.remember(second, proposal(second))
    assert cache.series_for_paths([first], "Superman & Lois") is None
    assert cache.series_for_paths([second], "Superman & Lois") is not None
    cache.remember(second, None)
    assert cache.series_for_paths([second], "Superman & Lois") is None


def test_folder_search_does_not_stat_unrelated_series(tmp_path, monkeypatch):
    from dragontools.rules.move_series_directories import find_series_dir_candidates

    target = tmp_path / "Superman & Lois"
    target.mkdir()
    for number in range(100):
        (tmp_path / f"Other series {number}").mkdir()
    original = Path.is_dir
    calls = []

    def checked(path):
        assert not path.name.startswith("Other series"), "Unrelated NAS directory was probed"
        calls.append(path)
        return original(path)

    monkeypatch.setattr(Path, "is_dir", checked)
    assert find_series_dir_candidates(str(tmp_path), "Superman & Lois") == [str(target)]
    assert calls and len(calls) <= 2
