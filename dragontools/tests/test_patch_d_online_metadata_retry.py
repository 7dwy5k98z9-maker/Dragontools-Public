from __future__ import annotations

from email.message import Message
from io import BytesIO
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request

import pytest


def _disable_retry_waits(monkeypatch) -> None:
    import dragontools.core.online_metadata_retry as retry

    monkeypatch.setattr(retry.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(retry.random, "uniform", lambda _start, _end: 0.0)


def test_retry_policy_retries_transient_failure_three_total_attempts(monkeypatch):
    from dragontools.core.online_metadata_retry import (
        RetryableOnlineMetadataError,
        retry_online_metadata_call,
    )

    _disable_retry_waits(monkeypatch)
    calls = 0

    def operation():
        nonlocal calls
        calls += 1
        raise RetryableOnlineMetadataError("temporär")

    with pytest.raises(Exception, match=r"temporär.*3 Versuchen"):
        retry_online_metadata_call(operation, provider="Test")

    assert calls == 3


def test_retry_after_overrides_shorter_exponential_backoff(monkeypatch):
    import dragontools.core.online_metadata_retry as retry

    delays: list[float] = []
    monkeypatch.setattr(retry.time, "sleep", delays.append)
    monkeypatch.setattr(retry.random, "uniform", lambda _start, _end: 0.0)
    calls = 0

    def operation():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise retry.RetryableOnlineMetadataError("429", retry_after=4.0)
        return {"ok": True}

    assert retry.retry_online_metadata_call(operation, provider="Test") == {"ok": True}
    assert delays == [4.0]


def test_permanent_metadata_error_is_not_retried(monkeypatch):
    from dragontools.core.online_metadata import OnlineMetadataError
    from dragontools.core.online_metadata_retry import retry_online_metadata_call

    _disable_retry_waits(monkeypatch)
    calls = 0

    def operation():
        nonlocal calls
        calls += 1
        raise OnlineMetadataError("permanent")

    with pytest.raises(OnlineMetadataError, match="permanent"):
        retry_online_metadata_call(operation, provider="Test")

    assert calls == 1


def test_http_429_is_classified_retryable_and_reads_retry_after(monkeypatch):
    import dragontools.core.online_metadata_http as http
    from dragontools.core.online_metadata_retry import RetryableOnlineMetadataError

    headers = Message()
    headers["Retry-After"] = "2.5"

    def fail(_request, timeout):
        raise HTTPError(
            "https://example.invalid",
            429,
            "Too Many Requests",
            headers,
            BytesIO(b'{"status":"rate limited"}'),
        )

    monkeypatch.setattr(http, "urlopen", fail)

    with pytest.raises(RetryableOnlineMetadataError) as exc_info:
        http.request_json(Request("https://example.invalid"), 1, label="TMDB")

    assert exc_info.value.retry_after == 2.5
    assert "HTTP 429" in str(exc_info.value)


def test_http_401_is_auth_error_and_not_retryable(monkeypatch):
    import dragontools.core.online_metadata_http as http
    from dragontools.core.online_metadata import OnlineMetadataAuthError

    def fail(_request, timeout):
        raise HTTPError(
            "https://example.invalid",
            401,
            "Unauthorized",
            Message(),
            BytesIO(b"{}"),
        )

    monkeypatch.setattr(http, "urlopen", fail)

    with pytest.raises(OnlineMetadataAuthError, match="HTTP 401"):
        http.request_json(
            Request("https://example.invalid"),
            1,
            label="TMDB",
            auth_error_template="TMDB Zugang abgelehnt (HTTP {code}).",
        )


def test_tmdb_transport_retries_injected_transient_get(monkeypatch, tmp_path):
    from dragontools.core.online_metadata import OnlineMetadataConfig, TmdbClient
    from dragontools.core.online_metadata_retry import RetryableOnlineMetadataError

    _disable_retry_waits(monkeypatch)
    calls = 0

    def fake_get(_url, _headers, _timeout):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RetryableOnlineMetadataError("TMDB ist kurz nicht erreichbar")
        return {"results": []}

    client = TmdbClient(
        OnlineMetadataConfig(
            tmdb_enabled=True,
            tmdb_read_token="token",
            cache_enabled=False,
        ),
        cache_dir=tmp_path,
        http_get=fake_get,
    )

    assert client.search_movies("Nicht vorhanden") == []
    assert calls == 3


def test_tvdb_login_retries_transient_failure(monkeypatch, tmp_path):
    from dragontools.core.online_metadata import OnlineMetadataConfig, TheTvdbClient
    from dragontools.core.online_metadata_retry import RetryableOnlineMetadataError

    _disable_retry_waits(monkeypatch)
    calls = 0

    def fake_post(_url, _headers, _payload, _timeout):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RetryableOnlineMetadataError("TheTVDB Login temporär nicht erreichbar")
        return {"data": {"token": "token-after-retry"}}

    client = TheTvdbClient(
        OnlineMetadataConfig(
            tvdb_enabled=True,
            tvdb_api_key="key",
            cache_enabled=False,
        ),
        cache_dir=tmp_path,
        http_get=lambda *_args: {"data": []},
        http_post=fake_post,
    )

    assert client._auth_token() == "token-after-retry"
    assert calls == 3


def test_composite_raises_when_all_providers_fail_but_not_when_one_succeeds():
    from dragontools.core.online_metadata import OnlineMetadataConfig, OnlineMetadataError
    from dragontools.core.online_metadata_service import CompositeMetadataClient

    class FailingClient:
        config = OnlineMetadataConfig()

        def __init__(self, label: str):
            self.provider_label = label

        def search_movies(self, _query, *, year=None, language=None):
            raise OnlineMetadataError(f"{self.provider_label} API nicht erreichbar")

    class EmptyClient(FailingClient):
        def search_movies(self, _query, *, year=None, language=None):
            return []

    all_failed = CompositeMetadataClient((FailingClient("TMDB"), FailingClient("TheTVDB")))
    with pytest.raises(OnlineMetadataError, match="Alle konfigurierten.*TMDB.*TheTVDB"):
        all_failed.search_movies("Test")

    one_responded = CompositeMetadataClient((FailingClient("TMDB"), EmptyClient("TheTVDB")))
    assert one_responded.search_movies("Test") == []
