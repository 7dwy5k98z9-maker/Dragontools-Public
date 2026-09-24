from __future__ import annotations

from pathlib import Path

from dragontools.core.movie_renamer import (
    build_series_rename_proposal,
    parse_movie_release_name,
    parse_series_release_name,
)
from dragontools.core.online_metadata_common import parse_series_query
from dragontools.rules import renamer_rules


def _stars_rules(monkeypatch):
    rules = renamer_rules.migrate_renamer_rules({"release_groups": ["STARS"]})
    monkeypatch.setattr(renamer_rules, "_RULES_CACHE", rules)


def test_bare_e_release_is_series_and_defaults_to_season_one(monkeypatch):
    _stars_rules(monkeypatch)
    name = "stars-dragon.ball.daima.d.e19.1080p.mkv"

    movie = parse_movie_release_name(name)
    parsed = parse_series_release_name(name)

    assert movie.is_probable_series is True
    assert parsed is not None
    assert parsed.release_group == "STARS"
    assert parsed.season == 1
    assert parsed.episode == 19
    assert parsed.season_missing is False
    assert "e19" not in parse_series_query(name).title.casefold()
    assert any("Staffel 1" in warning for warning in parsed.warnings)


def test_bare_e_provider_lookup_uses_season_one(monkeypatch, tmp_path: Path):
    _stars_rules(monkeypatch)
    source = tmp_path / "stars-dragon.ball.daima.d.e19.1080p.mkv"
    source.write_bytes(b"x")
    seen = {}

    def resolver(series: str, season: int, episode: int, year: int | None):
        seen.update(series=series, season=season, episode=episode, year=year)
        return []

    proposal = build_series_rename_proposal(source, resolver=resolver)

    assert seen["season"] == 1
    assert seen["episode"] == 19
    assert proposal.parsed.season == 1
    assert proposal.parsed.episode == 19


def test_manual_season_override_also_replaces_explicit_or_inferred_season(monkeypatch, tmp_path: Path):
    _stars_rules(monkeypatch)
    source = tmp_path / "STARS.The.Show.S01E19.mkv"
    source.write_bytes(b"x")
    seen = {}

    def resolver(series: str, season: int, episode: int, year: int | None):
        seen.update(series=series, season=season, episode=episode, year=year)
        return []

    proposal = build_series_rename_proposal(source, resolver=resolver, season_override=3)

    assert seen["season"] == 3
    assert seen["episode"] == 19
    assert proposal.parsed.season == 3
    assert any("Staffel 3 manuell gesetzt" in warning for warning in proposal.parsed.warnings)


def test_manual_season_button_is_wired_into_renamer():
    root = Path(__file__).resolve().parents[1]
    view = (root / "gui" / "movie_renamer_view.py").read_text(encoding="utf-8")
    widget = (root / "gui" / "movie_renamer_widget.py").read_text(encoding="utf-8")
    state = (root / "gui" / "movie_renamer_view_state.py").read_text(encoding="utf-8")

    assert 'self.edit_season_btn = QPushButton("🗓 Staffel ändern")' in view
    assert "self.edit_season_btn.clicked.connect(self._actions.edit_selected_season)" in widget
    assert "self.edit_season_btn" in state
