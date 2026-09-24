from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from dragontools.core.online_metadata import OnlineMetadataConfig, TheTvdbClient, TmdbClient
from dragontools.core.settings_jellyfin import DEFAULT_JELLYFIN_NOTIFY_AFTER_RENAME
from dragontools.core.watch_folder import WatchFolderRule, WatchFolderScanner


PACKAGE = Path(__file__).resolve().parents[1]


def _watch_rule(path: Path) -> WatchFolderRule:
    rule = WatchFolderRule.from_mapping(
        {
            "rule_id": "ae",
            "name": "AE",
            "path": str(path),
            "recursive": True,
            "codec": "h265",
            "auto_start": True,
            "enabled": True,
        }
    )
    assert rule is not None
    return rule


def test_watch_acknowledges_post_conversion_signature_for_in_place_replace(tmp_path: Path) -> None:
    source = tmp_path / "episode.mkv"
    source.write_bytes(b"before")
    scanner = WatchFolderScanner(stable_seconds=0)
    candidate = scanner.scan([_watch_rule(tmp_path)], now=0)[0]

    # Simulate Strip-Only/overwrite-original replacing the watched source.
    source.write_bytes(b"after-conversion-is-different")
    stat = source.stat()
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

    final_signature = scanner.acknowledge_current(candidate)
    assert final_signature != candidate.signature
    assert scanner.scan([_watch_rule(tmp_path)], now=1) == []


def test_watch_overwrite_is_not_requeued_after_sixty_second_stability_window(tmp_path: Path) -> None:
    source = tmp_path / "episode.mkv"
    source.write_bytes(b"before")
    scanner = WatchFolderScanner(stable_seconds=60)
    rule = _watch_rule(tmp_path)

    assert scanner.scan([rule], now=0) == []
    candidate = scanner.scan([rule], now=61)[0]

    # Strip-Only replaces the same pathname with the final stripped file.
    source.write_bytes(b"after-strip-only")
    stat = source.stat()
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    scanner.acknowledge_current(candidate)

    # This is the exact former feedback-loop window: after another 60+ seconds
    # DragonTools must still recognise its own output as already handled.
    assert scanner.scan([rule], now=130) == []


def test_watch_controller_uses_current_signature_after_success() -> None:
    source = (PACKAGE / "gui/watch_folder_controller.py").read_text(encoding="utf-8")
    assert "acknowledge_current(candidate)" in source
    assert "self._scanner.acknowledge(candidate)" not in source


def test_tmdb_renamer_batches_multiple_episodes_by_season(tmp_path: Path) -> None:
    calls = {"search": 0, "season": 0, "episode": 0}

    def fake_get(url: str, headers: dict[str, str], timeout: int):
        parsed = urlparse(url)
        if parsed.path.endswith("/search/tv"):
            calls["search"] += 1
            return {
                "results": [
                    {
                        "id": 4242,
                        "name": "Batch Show",
                        "original_name": "Batch Show",
                        "first_air_date": "2024-01-01",
                        "popularity": 100,
                    }
                ]
            }
        if parsed.path.endswith("/tv/4242/season/1"):
            calls["season"] += 1
            return {
                "id": 100,
                "season_number": 1,
                "episodes": [
                    {"id": 101, "episode_number": 1, "name": "One", "air_date": "2024-01-01"},
                    {"id": 102, "episode_number": 2, "name": "Two", "air_date": "2024-01-08"},
                ],
            }
        if "/episode/" in parsed.path:
            calls["episode"] += 1
            raise AssertionError(f"Renamer should not need per-episode TMDB call: {url}")
        raise AssertionError(url)

    client = TmdbClient(
        OnlineMetadataConfig(
            series_provider="tmdb",
            tmdb_enabled=True,
            tmdb_read_token="token",
            language="de-DE",
            fallback_language="en-US",
            cache_enabled=False,
        ),
        cache_dir=tmp_path,
        http_get=fake_get,
    )

    first = client.resolve_renamer_episode_candidates("Batch Show - S01E01.mkv")
    search_after_first = calls["search"]
    second = client.resolve_renamer_episode_candidates("Batch Show - S01E02.mkv")

    assert first and first[0].title == "One"
    assert second and second[0].title == "Two"
    assert calls["season"] == 1
    assert calls["episode"] == 0
    assert calls["search"] == search_after_first


def test_tvdb_renamer_reuses_series_search_and_full_episode_batch(tmp_path: Path) -> None:
    calls = {"login": 0, "search": 0, "series": 0, "episodes": 0}

    def fake_post(url: str, headers: dict[str, str], payload: dict, timeout: int):
        calls["login"] += 1
        return {"data": {"token": "token"}}

    def fake_get(url: str, headers: dict[str, str], timeout: int):
        parsed = urlparse(url)
        if parsed.path.endswith("/search"):
            calls["search"] += 1
            return {"data": [{"id": 5252, "name": "Batch Show", "year": "2024", "score": 100}]}
        if parsed.path.endswith("/series/5252/extended"):
            calls["series"] += 1
            return {"data": {"id": 5252, "name": "Batch Show", "firstAired": "2024-01-01"}}
        if "/series/5252/episodes/default/" in parsed.path:
            calls["episodes"] += 1
            return {
                "data": {
                    "episodes": [
                        {"id": 201, "seasonNumber": 1, "number": 1, "name": "One"},
                        {"id": 202, "seasonNumber": 1, "number": 2, "name": "Two"},
                    ]
                }
            }
        raise AssertionError(url)

    client = TheTvdbClient(
        OnlineMetadataConfig(
            series_provider="thetvdb",
            tvdb_enabled=True,
            tvdb_api_key="api",
            language="de-DE",
            fallback_language="en-US",
            cache_enabled=False,
        ),
        cache_dir=tmp_path,
        http_get=fake_get,
        http_post=fake_post,
    )

    first = client.resolve_renamer_episode_candidates("Batch Show - S01E01.mkv")
    search_after_first = calls["search"]
    second = client.resolve_renamer_episode_candidates("Batch Show - S01E02.mkv")

    assert first and first[0].title == "One"
    assert second and second[0].title == "Two"
    assert calls["episodes"] == 1
    assert calls["series"] == 1
    assert calls["search"] == search_after_first


def test_movie_renamer_prefers_provider_batch_resolver() -> None:
    source = (PACKAGE / "core/movie_renamer_candidate_resolvers.py").read_text(encoding="utf-8")
    assert '"resolve_renamer_episode_candidates"' in source


def test_renamer_jellyfin_is_opt_in_targeted_only_and_never_fullscan() -> None:
    assert DEFAULT_JELLYFIN_NOTIFY_AFTER_RENAME is False
    source = (PACKAGE / "gui/jellyfin_refresh_dispatch.py").read_text(encoding="utf-8")
    assert 'if trigger == "rename":' in source
    assert 'refresh_mode = "targeted"' in source
    assert "fallback_full_scan = False" in source


def test_jellyfin_settings_explain_move_only_fullscan_contract() -> None:
    source = (PACKAGE / "gui/settings_sections/jellyfin.py").read_text(encoding="utf-8")
    assert "Renamer startet dabei niemals einen vollständigen Bibliotheksscan" in source
    assert "Vollscan/Fallback ist nur dem Move-Workflow vorbehalten" in source
