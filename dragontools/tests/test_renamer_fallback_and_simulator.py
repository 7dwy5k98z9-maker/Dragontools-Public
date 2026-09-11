from __future__ import annotations

from types import SimpleNamespace


def test_series_renamer_uses_configured_45_percent_fallback(tmp_path):
    from dragontools.core.movie_renamer import build_series_rename_proposal

    source = tmp_path / "My.Instant.Death.Ability.Is.Overpowered.2024.S01E01.mkv"
    source.write_text("video", encoding="utf-8")

    def resolver(series: str, season: int, episode: int, year: int | None):
        assert series == "My Instant Death Ability Is Overpowered"
        assert season == 1
        assert episode == 1
        assert year == 2024
        return [{
            "series": (
                "My Instant Death Ability Is So Overpowered, "
                "No One in This Other World Stands a Chance Against Me!"
            ),
            "season": 1,
            "episode": 1,
            "episode_title": "Instant Death Cheat",
            "year": 2024,
            "provider": "thetvdb",
            "provider_id": 355774,
            "episode_id": 1001,
        }]

    proposal = build_series_rename_proposal(source, resolver=resolver)

    assert proposal.selected is not None
    assert proposal.selected.provider == "thetvdb"
    assert 0.45 <= proposal.confidence < 0.60
    assert proposal.minimum_score_used == 0.45
    assert proposal.status == "fallback_review"
    assert proposal.can_auto_accept is False
    assert any("45 %" in warning for warning in proposal.warnings)


def test_renamer_fallback_scores_are_individually_configurable(monkeypatch):
    from dragontools.rules import renamer_rules

    custom = renamer_rules.migrate_renamer_rules({
        "matching": {
            "minimum_candidate_score": 0.70,
            "fallback_candidate_scores": [0.52, 0.35],
        }
    })
    monkeypatch.setattr(renamer_rules, "_RULES_CACHE", custom)

    assert renamer_rules.minimum_candidate_score() == 0.70
    assert renamer_rules.fallback_candidate_scores() == (0.52, 0.35)
    assert renamer_rules.candidate_score_stages() == (0.70, 0.52, 0.35)
    assert renamer_rules.candidate_discovery_floor() == 0.30


def test_lowest_fallback_marks_close_candidates_as_ambiguous(monkeypatch):
    from dragontools.core.movie_renamer_matching import candidate_status
    from dragontools.rules import renamer_rules

    custom = renamer_rules.migrate_renamer_rules({
        "matching": {
            "minimum_candidate_score": 0.60,
            "fallback_candidate_scores": [0.45, 0.30],
        }
    })
    monkeypatch.setattr(renamer_rules, "_RULES_CACHE", custom)

    candidates = [SimpleNamespace(score=0.34), SimpleNamespace(score=0.31)]
    status, warning = candidate_status(candidates, threshold=0.30, target_exists=False)

    assert status == "fallback_ambiguous"
    assert warning and "manuell prüfen" in warning


def test_rules_preview_calculates_downscale_target_resolution():
    from dragontools.core.rules_preview import _build_target_video_preview

    media_info = SimpleNamespace(
        primary_video=SimpleNamespace(width=1920, height=1080),
    )

    full_hd = _build_target_video_preview(
        media_info,
        {},
        {"scale_mode": "1080p"},
        autocrop_enabled=False,
    )
    hd = _build_target_video_preview(
        media_info,
        {},
        {"scale_mode": "720p"},
        autocrop_enabled=False,
    )
    cropped = _build_target_video_preview(
        media_info,
        {},
        {"scale_mode": "1080p"},
        autocrop_enabled=True,
    )

    assert full_hd["resolution"] == "1920x1080"
    assert hd["resolution"] == "1280x720"
    assert cropped["resolution"] == "1920x1080"
    assert cropped["autocrop_pending"] is True
