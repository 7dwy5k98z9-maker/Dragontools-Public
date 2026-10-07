from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from dragontools.core.movie_renamer import (
    build_movie_rename_proposal,
    build_series_rename_proposal,
    rename_movie_file,
)
from dragontools.core.movie_renamer_candidate_scoring import _compare_text


def _journal_under(monkeypatch, tmp_path: Path) -> None:
    from dragontools.core import sidecar_journal

    monkeypatch.setattr(sidecar_journal, "app_documents_dir", lambda root=None: tmp_path / "docs")


def test_unicode_comparison_key_preserves_non_latin_titles() -> None:
    assert _compare_text("劇場版モノノ怪") == "劇場版モノノ怪"
    assert _compare_text("魔道祖师") == "魔道祖师"


def test_movie_match_uses_original_non_latin_title_not_only_localized_title() -> None:
    proposal = build_movie_rename_proposal(
        "劇場版モノノ怪.2024.mkv",
        resolver=lambda _query, _year: [
            {
                "title": "Mononoke the Movie: Phantom in the Rain",
                "original_title": "劇場版モノノ怪 唐傘",
                "release_date": "2024-07-26",
                "id": 123,
            }
        ],
        # The provider original title intentionally contains an added subtitle;
        # it must still score materially above the old empty-key score of 0.
        show_all_candidates=True,
    )
    assert proposal.candidates
    assert proposal.candidates[0].score > 0.45


def test_movie_exact_original_non_latin_title_can_be_selected_normally() -> None:
    proposal = build_movie_rename_proposal(
        "劇場版モノノ怪.2024.mkv",
        resolver=lambda _query, _year: [
            {
                "title": "Mononoke the Movie",
                "original_title": "劇場版モノノ怪",
                "release_date": "2024-07-26",
                "id": 123,
            }
        ],
    )
    assert proposal.selected is not None
    assert proposal.selected.score >= 0.99
    assert proposal.target_name == "Mononoke the Movie (2024).mkv"


def test_series_match_uses_original_show_name_for_non_latin_query() -> None:
    raw = SimpleNamespace(
        show_name="Mononoke",
        original_show_name="モノノ怪",
        season_number=1,
        episode_number=1,
        title="Zashiki-warashi",
        first_air_year=2007,
        provider="tmdb",
        series_provider_id=111,
        episode_provider_id=222,
        title_is_fallback=False,
    )
    proposal = build_series_rename_proposal(
        "モノノ怪 - S01E01.mkv",
        resolver=lambda *_args: [raw],
    )
    assert proposal.selected is not None
    assert proposal.selected.score >= 0.99
    assert proposal.selected.series == "Mononoke"


def test_renamer_rejects_container_extension_change(tmp_path: Path) -> None:
    source = tmp_path / "Film.mkv"
    source.write_bytes(b"mkv")

    with pytest.raises(ValueError, match="Container"):
        rename_movie_file(source, "Film.mp4")

    assert source.read_bytes() == b"mkv"
    assert not (tmp_path / "Film.mp4").exists()


def test_rename_moves_media_nfo_subtitles_and_trickplay_together(tmp_path: Path, monkeypatch) -> None:
    _journal_under(monkeypatch, tmp_path)
    source = tmp_path / "Alt.mkv"
    nfo = tmp_path / "Alt.nfo"
    sub = tmp_path / "Alt.de.srt"
    trickplay = tmp_path / "Alt.trickplay"
    source.write_bytes(b"video")
    nfo.write_text("nfo", encoding="utf-8")
    sub.write_text("sub", encoding="utf-8")
    trickplay.mkdir()
    (trickplay / "0.jpg").write_bytes(b"jpg")

    target = rename_movie_file(source, "Neu.mkv")

    assert target == tmp_path / "Neu.mkv"
    assert target.read_bytes() == b"video"
    assert (tmp_path / "Neu.nfo").read_text(encoding="utf-8") == "nfo"
    assert (tmp_path / "Neu.de.srt").read_text(encoding="utf-8") == "sub"
    assert (tmp_path / "Neu.trickplay" / "0.jpg").read_bytes() == b"jpg"
    assert not source.exists()
    assert not nfo.exists()
    assert not sub.exists()
    assert not trickplay.exists()


def test_existing_companion_target_blocks_entire_rename_before_mutation(tmp_path: Path, monkeypatch) -> None:
    _journal_under(monkeypatch, tmp_path)
    source = tmp_path / "Alt.mkv"
    source.write_bytes(b"video")
    old_sub = tmp_path / "Alt.de.srt"
    old_sub.write_text("old", encoding="utf-8")
    new_sub = tmp_path / "Neu.de.srt"
    new_sub.write_text("user", encoding="utf-8")

    with pytest.raises(FileExistsError, match="Begleitdatei"):
        rename_movie_file(source, "Neu.mkv")

    assert source.read_bytes() == b"video"
    assert old_sub.read_text(encoding="utf-8") == "old"
    assert new_sub.read_text(encoding="utf-8") == "user"
    assert not (tmp_path / "Neu.mkv").exists()


def test_video_publish_failure_rolls_sidecars_back(tmp_path: Path, monkeypatch) -> None:
    _journal_under(monkeypatch, tmp_path)
    source = tmp_path / "Alt.mkv"
    source.write_bytes(b"video")
    old_sub = tmp_path / "Alt.de.srt"
    old_sub.write_text("old", encoding="utf-8")

    import dragontools.core.movie_renamer_parsing as parsing

    def fail_publish(_source, _target):
        raise FileExistsError("late target")

    monkeypatch.setattr(parsing, "publish_staged_no_replace", fail_publish)

    with pytest.raises(FileExistsError, match="late target"):
        rename_movie_file(source, "Neu.mkv")

    assert source.read_bytes() == b"video"
    assert old_sub.read_text(encoding="utf-8") == "old"
    assert not (tmp_path / "Neu.de.srt").exists()


def test_metadata_browser_new_search_and_kind_switch_clear_active_context_statically() -> None:
    path = Path(__file__).parents[1] / "gui" / "movie_renamer_metadata_browser.py"
    source = path.read_text(encoding="utf-8")
    ast.parse(source)
    assert "def _clear_active_metadata_context" in source
    # Both a kind switch and a fresh provider query invalidate old episode rows.
    assert source.count("self._clear_active_metadata_context()") >= 2
    # Existing mappings, not stale active-hit state, decide whether switching
    # to another series requires confirmation.
    assert "mapped_hits = {" in source
    assert "mapped_hits != {selected_hit_key}" in source


def test_table_preflight_contains_container_suffix_guard_statically() -> None:
    path = Path(__file__).parents[1] / "gui" / "movie_renamer_table_controller.py"
    source = path.read_text(encoding="utf-8")
    ast.parse(source)
    assert "Container-Endung darf im Renamer nicht geändert werden" in source


def test_manual_episode_zero_is_rejected_consistently() -> None:
    from dragontools.core.movie_renamer_parsing import parse_series_release_name
    from dragontools.core.movie_renamer_season_override import apply_series_episode_override

    parsed = parse_series_release_name("Example.Show.S01E02.mkv")
    assert parsed is not None
    unchanged, issue = apply_series_episode_override(parsed, 0)
    assert issue == "invalid"
    assert unchanged.episode == 2


def test_normal_series_parser_preserves_double_episode_identity() -> None:
    from dragontools.core.movie_renamer_parsing import parse_series_release_name

    parsed = parse_series_release_name("Example.Show.S01E03E04.mkv")
    assert parsed is not None
    assert parsed.episode_numbers == (3, 4)


def test_normal_series_proposal_keeps_double_episode_code_and_requires_review() -> None:
    raw = SimpleNamespace(
        show_name="Example Show",
        original_show_name="Example Show",
        season_number=1, episode_number=3, title="First Part", first_air_year=2024,
        provider="tmdb", series_provider_id=1, episode_provider_id=3, title_is_fallback=False,
    )
    proposal = build_series_rename_proposal(
        "Example.Show.S01E03E04.mkv", resolver=lambda *_args: [raw]
    )
    assert proposal.selected is not None
    assert "S01E03E04" in proposal.target_name
    assert proposal.status == "manual_review"
    assert any("Mehrfachfolge" in warning for warning in proposal.warnings)


def test_movie_provider_alias_can_match_manual_title() -> None:
    proposal = build_movie_rename_proposal(
        "Spirited Away.2001.mkv",
        resolver=lambda _query, _year: [{
            "name": "Sen to Chihiro no Kamikakushi",
            "originalName": "千と千尋の神隠し",
            "aliases": [{"language": "eng", "name": "Spirited Away"}],
            "year": "2001",
            "provider": "thetvdb",
            "provider_id": 99,
        }],
    )
    assert proposal.selected is not None
    assert proposal.selected.score >= 0.99


def test_non_latin_title_exception_applies(monkeypatch):
    from dragontools.rules import renamer_rules

    rules = renamer_rules.migrate_renamer_rules({
        "title_exceptions": [
            {"source": "劇場版モノノ怪 シリーズ", "replacement": "Mononoke Movie Series"}
        ]
    })
    monkeypatch.setattr(renamer_rules, "_RULES_CACHE", rules)

    assert renamer_rules.apply_title_exception("劇場版モノノ怪 シリーズ") == "Mononoke Movie Series"
