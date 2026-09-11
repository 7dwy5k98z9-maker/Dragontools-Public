from __future__ import annotations

from dragontools.core.paths import (
    join_user_path,
    normalize_user_path,
    path_compare_key,
    path_is_same_or_child,
    user_path_name,
    user_path_parent,
    user_path_stem,
)


def test_unc_path_is_normalized_without_host_reinterpretation() -> None:
    path = r"\\TestServer\video\Serien\TV\American Dad! (2005)"

    assert normalize_user_path(path) == path
    assert user_path_name(path) == "American Dad! (2005)"
    assert user_path_parent(path) == r"\\TestServer\video\Serien\TV"


def test_forward_slash_unc_and_backslash_unc_compare_equal() -> None:
    forward = "//testserver/video/Serien/Anime"
    backslash = r"\\TestServer\video\Serien\Anime"

    assert normalize_user_path(forward) == r"\\testserver\video\Serien\Anime"
    assert path_compare_key(forward) == path_compare_key(backslash)


def test_drive_path_join_keeps_windows_separator() -> None:
    assert join_user_path(r"D:\Anime", "Stargate Atlantis") == r"D:\Anime\Stargate Atlantis"
    assert join_user_path(r"D:\Anime", "Stargate Atlantis", "Staffel 01") == (
        r"D:\Anime\Stargate Atlantis\Staffel 01"
    )


def test_windows_filename_helpers_are_host_independent() -> None:
    path = r"C:\Eingang\Meine Serie - S01E02.mkv"

    assert user_path_name(path) == "Meine Serie - S01E02.mkv"
    assert user_path_stem(path) == "Meine Serie - S01E02"
    assert user_path_parent(path) == r"C:\Eingang"


def test_path_child_check_is_case_insensitive_for_windows_paths() -> None:
    base = r"\\TestServer\video\Serien\TV"
    child = r"//TESTSERVER/video/serien/tv/American Dad! (2005)"
    sibling = r"\\TestServer\video\Serien\TV_alt\American Dad! (2005)"

    assert path_is_same_or_child(child, base) is True
    assert path_is_same_or_child(sibling, base) is False


def test_jellyfin_posix_path_helpers_keep_forward_slashes() -> None:
    path = "/TVSerien/Watson (2025)/Staffel 01/Watson - S01E01.mkv"

    assert user_path_name(path) == "Watson - S01E01.mkv"
    assert user_path_parent(path) == "/TVSerien/Watson (2025)/Staffel 01"
    assert join_user_path("/TVSerien", "Watson (2025)") == "/TVSerien/Watson (2025)"


def test_move_rules_use_windows_filename_and_target_syntax() -> None:
    from dragontools.rules.move_rules import move_safe_stem, resolve_film_target_for_path

    source = r"C:\Eingang\Mein Film_H265.mkv"

    assert move_safe_stem(source) == "Mein Film"
    assert resolve_film_target_for_path(source, base_path=r"D:\Filme") == r"D:\Filme\M\Mein Film"
