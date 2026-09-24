from __future__ import annotations

import json
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError

import pytest

from dragontools.core.jellyfin_api import JellyfinApiError, JellyfinClient, normalize_server_url
from dragontools.core.jellyfin_full_scan_guard import reset_full_scan_guard_for_tests
from dragontools.core.jellyfin_refresh_service import (
    JellyfinRefreshConfig,
    build_move_updates,
    build_rename_updates,
    execute_refresh,
    merge_refresh_mappings,
    prepare_targeted_updates,
)
from dragontools.core.media_library_path_mappings import map_local_to_external_path
from dragontools.core.media_library_types import PathMapping


class _Response:
    def __init__(self, payload=b"") -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


def _http_error(url: str, code: int, retry_after: str | None = None) -> HTTPError:
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return HTTPError(url, code, "error", headers, None)


@pytest.fixture(autouse=True)
def _reset_jellyfin_full_scan_guard() -> None:
    reset_full_scan_guard_for_tests()



def test_normalize_server_url_adds_http_and_preserves_base_path() -> None:
    assert normalize_server_url("192.168.1.5:8096/jellyfin/") == "http://192.168.1.5:8096/jellyfin"
    assert normalize_server_url("https://media.example/jellyfin/") == "https://media.example/jellyfin"


def test_get_system_info_uses_modern_mediabrowser_authorization_header() -> None:
    captured = {}

    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["timeout"] = timeout
        payload = json.dumps({"ServerName": "NAS", "Version": "12.0.0", "OperatingSystem": "Linux"}).encode()
        return _Response(payload)

    info = JellyfinClient("http://nas:8096", "secret-token", opener=opener).get_system_info()

    assert info.server_name == "NAS"
    assert info.version == "12.0.0"
    assert captured["url"] == "http://nas:8096/System/Info"
    authorization = captured["headers"]["Authorization"]
    assert authorization.startswith("MediaBrowser ")
    assert 'Token="secret-token"' in authorization


def test_get_physical_paths_reads_jellyfin_server_namespace() -> None:
    captured = {}

    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        return _Response(json.dumps(["/TVSerien", "/Anime", "/Filme", "/Anime"]).encode())

    paths = JellyfinClient("http://nas", "key", opener=opener).get_physical_paths()

    assert paths == ["/TVSerien", "/Anime", "/Filme"]
    assert captured == {"url": "http://nas/Library/PhysicalPaths", "method": "GET"}


def test_transient_http_error_retries_three_total_attempts() -> None:
    calls = []
    sleeps = []

    def opener(request, timeout):
        calls.append(request.full_url)
        if len(calls) < 3:
            raise _http_error(request.full_url, 503)
        return _Response(b'{"ServerName":"NAS","Version":"12"}')

    info = JellyfinClient(
        "http://nas:8096",
        "key",
        opener=opener,
        sleeper=sleeps.append,
    ).get_system_info()

    assert info.server_name == "NAS"
    assert len(calls) == 3
    assert sleeps == [0.5, 1.0]


def test_unauthorized_does_not_retry() -> None:
    calls = []

    def opener(request, timeout):
        calls.append(request.full_url)
        raise _http_error(request.full_url, 401)

    with pytest.raises(JellyfinApiError) as exc_info:
        JellyfinClient("http://nas", "bad", opener=opener, sleeper=lambda _delay: None).get_system_info()

    assert exc_info.value.status_code == 401
    assert len(calls) == 1


def test_retry_after_header_is_respected() -> None:
    sleeps = []
    calls = 0

    def opener(request, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _http_error(request.full_url, 429, "2.5")
        return _Response(b'{"ServerName":"NAS","Version":"12"}')

    JellyfinClient("http://nas", "key", opener=opener, sleeper=sleeps.append).get_system_info()
    assert sleeps == [2.5]


def test_notify_media_updates_posts_deduplicated_payload() -> None:
    captured = {}

    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _Response()

    client = JellyfinClient("http://nas", "key", opener=opener)
    client.notify_media_updates([
        {"Path": "/TV/A.mkv", "UpdateType": "Created"},
        {"Path": "/TV/A.mkv", "UpdateType": "Created"},
        {"Path": "/TV/B.mkv", "UpdateType": "Modified"},
    ])

    assert captured["url"] == "http://nas/Library/Media/Updated"
    assert captured["method"] == "POST"
    assert captured["payload"] == {"Updates": [
        {"Path": "/TV/A.mkv", "UpdateType": "Created"},
        {"Path": "/TV/B.mkv", "UpdateType": "Modified"},
    ]}


def test_refresh_library_posts_library_refresh_endpoint() -> None:
    captured = []

    def opener(request, timeout):
        captured.append((request.full_url, request.get_method()))
        return _Response()

    JellyfinClient("http://nas", "key", opener=opener).refresh_library()
    assert captured == [("http://nas/Library/Refresh", "POST")]

def test_library_scan_running_reads_scheduled_tasks() -> None:
    captured = []

    def opener(request, timeout):
        captured.append((request.full_url, request.get_method()))
        payload = [
            {"Key": "OtherTask", "Name": "Other", "State": "Running"},
            {"Key": "RefreshMediaLibraryTask", "Name": "Medien-Bibliothek scannen", "State": "Running"},
        ]
        return _Response(json.dumps(payload).encode())

    client = JellyfinClient("http://nas", "key", opener=opener)
    assert client.is_library_scan_running() is True
    assert captured == [("http://nas/ScheduledTasks", "GET")]


def test_library_scan_idle_is_not_reported_running() -> None:
    def opener(request, timeout):
        return _Response(json.dumps([
            {"Key": "RefreshMediaLibraryTask", "Name": "Scan Media Library", "State": "Idle"}
        ]).encode())

    assert JellyfinClient("http://nas", "key", opener=opener).is_library_scan_running() is False


def test_reverse_path_mapping_uses_longest_local_prefix_and_keeps_unmatched_path() -> None:
    mappings = [
        PathMapping("TV", "/TV", r"Z:\Media"),
        PathMapping("Anime", "/Anime", r"Z:\Media\Anime"),
    ]
    assert map_local_to_external_path(r"Z:\Media\Anime\Show\S01E01.mkv", mappings) == "/Anime/Show/S01E01.mkv"
    assert map_local_to_external_path(r"C:\Other\Movie.mkv", mappings) == r"C:\Other\Movie.mkv"


def test_merge_refresh_mappings_prefers_db_jellyfin_root_and_live_local_root() -> None:
    configured = [PathMapping("TV", "/wrong-tv", r"Z:\Serien")]
    stored = [PathMapping("TV", "/TVSerien", r"Y:\AlterPfad")]

    assert merge_refresh_mappings(configured, stored) == [
        PathMapping("TV", "/TVSerien", r"Z:\Serien")
    ]


def test_prepare_targeted_updates_validates_roots_and_adds_parent_folder_hint() -> None:
    prepared, parent_count = prepare_targeted_updates(
        [{
            "Path": "/TVSerien/Supernatural (2005)/Staffel 07/Supernatural - S07E05.mkv",
            "UpdateType": "Created",
        }],
        ["/TVSerien", "/Anime", "/Filme"],
    )

    assert parent_count == 1
    assert prepared == [
        {"Path": "/TVSerien/Supernatural (2005)/Staffel 07", "UpdateType": "Modified"},
        {
            "Path": "/TVSerien/Supernatural (2005)/Staffel 07/Supernatural - S07E05.mkv",
            "UpdateType": "Created",
        },
    ]


def test_prepare_targeted_updates_rejects_unmapped_windows_path() -> None:
    with pytest.raises(JellyfinApiError, match="Pfadvalidierung") as exc_info:
        prepare_targeted_updates(
            [{"Path": r"Z:\Serien\Show\S01E01.mkv", "UpdateType": "Created"}],
            ["/TVSerien", "/Anime", "/Filme"],
        )

    message = str(exc_info.value)
    assert "Z:/Serien/Show/S01E01.mkv" in message
    assert "/TVSerien" in message


def test_move_updates_include_only_successful_video_destinations_and_map_paths() -> None:
    mappings = [PathMapping("TV", "/TVSerien", r"Z:\TV")]
    updates = build_move_updates([
        {"kind": "video", "ok": True, "dest_path": r"Z:\TV\Show\S01E01.mkv"},
        {"kind": "video", "ok": False, "dest_path": r"Z:\TV\Show\S01E02.mkv"},
        {"kind": "nfo", "ok": True, "dest_path": r"Z:\TV\Show\tvshow.nfo"},
    ], mappings)
    assert updates == [{"Path": "/TVSerien/Show/S01E01.mkv", "UpdateType": "Created"}]




def test_move_updates_report_replaced_episode_paths_as_deleted_before_new_created() -> None:
    mappings = [PathMapping("TV", "/TVSerien", r"Z:\TV")]
    updates = build_move_updates([
        {
            "kind": "video",
            "ok": True,
            "dest_path": r"Z:\TV\Show\S01E01 - Neu.mkv",
            "episode_identity_replacement": True,
            "conflict_paths": [r"Z:\TV\Show\S01E01 - Alt.mkv"],
        },
    ], mappings)
    assert updates == [
        {"Path": "/TVSerien/Show/S01E01 - Alt.mkv", "UpdateType": "Deleted"},
        {"Path": "/TVSerien/Show/S01E01 - Neu.mkv", "UpdateType": "Created"},
    ]


def test_rename_updates_report_old_deleted_and_new_created() -> None:
    mappings = [PathMapping("TV", "/TVSerien", r"Z:\TV")]
    updates = build_rename_updates([
        (r"Z:\TV\Show\old.mkv", r"Z:\TV\Show\new.mkv"),
    ], mappings)
    assert updates == [
        {"Path": "/TVSerien/Show/old.mkv", "UpdateType": "Deleted"},
        {"Path": "/TVSerien/Show/new.mkv", "UpdateType": "Created"},
    ]


def test_execute_refresh_uses_targeted_notification_by_default() -> None:
    class Client:
        def __init__(self, server_url, api_key):
            self.calls = calls

        def get_physical_paths(self):
            return ["/TV"]

        def notify_media_updates(self, updates):
            self.calls.append(("targeted", list(updates)))

        def refresh_library(self):
            self.calls.append(("full", None))

    calls = []
    result = execute_refresh(
        JellyfinRefreshConfig("http://nas", "key"),
        [{"Path": "/TV/A.mkv", "UpdateType": "Created"}],
        client_factory=Client,
    )
    assert result.mode == "targeted"
    assert calls == [("targeted", [{"Path": "/TV/A.mkv", "UpdateType": "Created"}])]


def test_execute_refresh_full_mode_skips_targeted_notification() -> None:
    class Client:
        def __init__(self, server_url, api_key):
            pass

        def notify_media_updates(self, updates):
            calls.append("targeted")

        def refresh_library(self):
            calls.append("full")

    calls = []
    result = execute_refresh(
        JellyfinRefreshConfig("http://nas", "key", refresh_mode="full"),
        [{"Path": "/TV/A.mkv", "UpdateType": "Created"}],
        client_factory=Client,
    )
    assert result.mode == "full"
    assert calls == ["full"]


def test_execute_refresh_can_fallback_to_full_scan_after_targeted_failure() -> None:
    class Client:
        def __init__(self, server_url, api_key):
            pass

        def get_physical_paths(self):
            return ["/TV"]

        def notify_media_updates(self, updates):
            calls.append("targeted")
            raise JellyfinApiError("bad path")

        def refresh_library(self):
            calls.append("full")

    calls = []
    result = execute_refresh(
        JellyfinRefreshConfig("http://nas", "key", fallback_full_scan=True),
        [{"Path": "/TV/A.mkv", "UpdateType": "Created"}],
        client_factory=Client,
    )
    assert result.fallback_used is True
    assert calls == ["targeted", "full"]


def test_execute_refresh_invalid_path_falls_back_before_sending_targeted_request() -> None:
    class Client:
        def __init__(self, server_url, api_key):
            pass

        def get_physical_paths(self):
            calls.append("roots")
            return ["/TVSerien", "/Anime", "/Filme"]

        def notify_media_updates(self, updates):
            calls.append("targeted")

        def refresh_library(self):
            calls.append("full")

    calls = []
    result = execute_refresh(
        JellyfinRefreshConfig("http://nas", "key", fallback_full_scan=True),
        [{"Path": r"Z:\TV\Show\S01E01.mkv", "UpdateType": "Created"}],
        client_factory=Client,
    )

    assert result.fallback_used is True
    assert result.mode == "full"
    assert calls == ["roots", "full"]
    assert "Pfadvalidierung" in result.message


def test_execute_refresh_reuses_running_full_scan_instead_of_restarting_it() -> None:
    class Client:
        def __init__(self, server_url, api_key):
            pass

        def get_physical_paths(self):
            return ["/TV"]

        def notify_media_updates(self, updates):
            raise JellyfinApiError("targeted failed")

        def is_library_scan_running(self):
            calls.append("check")
            return True

        def refresh_library(self):
            calls.append("full")

    calls = []
    result = execute_refresh(
        JellyfinRefreshConfig("http://nas", "key", fallback_full_scan=True),
        [{"Path": "/TV/A.mkv", "UpdateType": "Created"}],
        client_factory=Client,
    )

    assert result.fallback_used is True
    assert result.full_scan_reused is True
    assert calls == ["check"]
    assert "weiterverwendet" in result.message


def test_execute_refresh_deduplicates_two_immediate_fallback_full_scans() -> None:
    class Client:
        def __init__(self, server_url, api_key):
            pass

        def get_physical_paths(self):
            return ["/TV"]

        def notify_media_updates(self, updates):
            calls.append("targeted")
            raise JellyfinApiError("targeted failed")

        def is_library_scan_running(self):
            calls.append("check")
            return False

        def refresh_library(self):
            calls.append("full")

    calls = []
    config = JellyfinRefreshConfig("http://nas", "key", fallback_full_scan=True)
    first = execute_refresh(
        config, [{"Path": "/TV/A.mkv", "UpdateType": "Created"}], client_factory=Client
    )
    second = execute_refresh(
        config, [{"Path": "/TV/B.mkv", "UpdateType": "Created"}], client_factory=Client
    )

    assert first.full_scan_reused is False
    assert second.full_scan_reused is True
    assert calls == ["targeted", "check", "full", "targeted"]
