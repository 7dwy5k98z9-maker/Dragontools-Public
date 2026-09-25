from __future__ import annotations

from pathlib import Path

from dragontools.core.movie_renamer import build_series_rename_proposal
from dragontools.core.movie_renamer_parsing import parse_series_release_name
from dragontools.core.movie_renamer_season_override import apply_series_episode_override


def test_manual_episode_override_replaces_detected_episode(tmp_path: Path):
    source = tmp_path / "Example.Show.S02E19.mkv"
    source.write_bytes(b"x")
    seen = {}

    def resolver(series: str, season: int, episode: int, year: int | None):
        seen.update(series=series, season=season, episode=episode, year=year)
        return []

    proposal = build_series_rename_proposal(
        source,
        resolver=resolver,
        episode_override=23,
    )

    assert seen["season"] == 2
    assert seen["episode"] == 23
    assert proposal.parsed.episode == 23
    assert any("Episode 23 manuell gesetzt" in item for item in proposal.parsed.warnings)


def test_season_and_episode_override_can_be_combined(tmp_path: Path):
    source = tmp_path / "Example.Show.S01E07.mkv"
    source.write_bytes(b"x")
    seen = {}

    def resolver(series: str, season: int, episode: int, year: int | None):
        seen.update(season=season, episode=episode)
        return []

    proposal = build_series_rename_proposal(
        source,
        resolver=resolver,
        season_override=4,
        episode_override=11,
    )

    assert seen == {"season": 4, "episode": 11}
    assert proposal.parsed.season == 4
    assert proposal.parsed.episode == 11


def test_episode_override_helper_rejects_out_of_range():
    parsed = parse_series_release_name("Example.Show.S01E02.mkv")
    assert parsed is not None
    unchanged, issue = apply_series_episode_override(parsed, 10000)
    assert issue == "invalid"
    assert unchanged.episode == 2


def test_episode_button_and_equal_three_by_five_toolbar_are_wired():
    root = Path(__file__).resolve().parents[1]
    view = (root / "gui" / "movie_renamer_view.py").read_text(encoding="utf-8")
    widget = (root / "gui" / "movie_renamer_widget.py").read_text(encoding="utf-8")
    state = (root / "gui" / "movie_renamer_view_state.py").read_text(encoding="utf-8")
    resolver = (root / "gui" / "movie_renamer_resolver.py").read_text(encoding="utf-8")

    assert 'self.edit_episode_btn = QPushButton("🔢 Episode ändern")' in view
    assert "self.edit_episode_btn.clicked.connect(self._actions.edit_selected_episode)" in widget
    assert "self.edit_episode_btn" in state
    assert "series_episode_override=episode_override" in resolver

    # Exactly 15 actions are arranged in 3 logical rows with equal 5-column stretch.
    toolbar_block = view.split("toolbar_rows = (", 1)[1].split("for row_index", 1)[0]
    assert toolbar_block.count("self.") == 15
    assert "for column_index in range(5):" in view
    assert "QSizePolicy.Policy.Expanding" in view
