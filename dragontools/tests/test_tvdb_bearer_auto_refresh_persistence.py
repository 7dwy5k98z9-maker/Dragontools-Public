# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest


class DummySettings:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.sync_calls = 0

    def value(self, key, default=None, *, type=None):
        value = self.values.get(key, default)
        if type is not None and value is not None:
            return type(value)
        return value

    def setValue(self, key, value):
        self.values[key] = value

    def sync(self):
        self.sync_calls += 1


def test_tvdb_login_persists_new_bearer_token(tmp_path):
    from dragontools.core.online_metadata import OnlineMetadataConfig, TheTvdbClient

    persisted: list[str] = []

    def fake_post(_url, _headers, payload, _timeout):
        assert payload == {"apikey": "api", "pin": "1234"}
        return {"data": {"token": "fresh-token"}}

    def fake_get(_url, headers, _timeout):
        assert headers["Authorization"] == "Bearer fresh-token"
        return {"data": []}

    client = TheTvdbClient(
        OnlineMetadataConfig(
            series_provider="thetvdb",
            tvdb_enabled=True,
            tvdb_api_key="api",
            tvdb_pin="1234",
            tvdb_bearer_token_store=persisted.append,
            cache_enabled=False,
        ),
        cache_dir=tmp_path,
        http_get=fake_get,
        http_post=fake_post,
    )

    assert client.search_series("Test") == []
    assert persisted == ["fresh-token"]


def test_tvdb_expired_manual_bearer_is_replaced_and_persisted(tmp_path):
    from dragontools.core.online_metadata import (
        OnlineMetadataAuthError,
        OnlineMetadataConfig,
        TheTvdbClient,
    )

    persisted: list[str] = []
    seen_auth: list[str] = []

    def fake_get(_url, headers, _timeout):
        auth = headers["Authorization"]
        seen_auth.append(auth)
        if auth == "Bearer old-manual-token":
            raise OnlineMetadataAuthError("expired")
        assert auth == "Bearer renewed-token"
        return {"data": []}

    def fake_post(_url, _headers, payload, _timeout):
        assert payload == {"apikey": "api"}
        return {"data": {"token": "renewed-token"}}

    client = TheTvdbClient(
        OnlineMetadataConfig(
            series_provider="thetvdb",
            tvdb_enabled=True,
            tvdb_api_key="api",
            tvdb_bearer_token="old-manual-token",
            tvdb_bearer_token_store=persisted.append,
            cache_enabled=False,
        ),
        cache_dir=tmp_path,
        http_get=fake_get,
        http_post=fake_post,
    )

    assert client.search_series("Test") == []
    assert seen_auth == ["Bearer old-manual-token", "Bearer renewed-token"]
    assert persisted == ["renewed-token"]


def test_tvdb_token_persistence_failure_does_not_break_valid_login(tmp_path, caplog):
    from dragontools.core.online_metadata import OnlineMetadataConfig, TheTvdbClient

    def broken_store(_token: str) -> None:
        raise OSError("settings locked")

    def fake_post(_url, _headers, _payload, _timeout):
        return {"data": {"token": "runtime-token"}}

    def fake_get(_url, headers, _timeout):
        assert headers["Authorization"] == "Bearer runtime-token"
        return {"data": []}

    client = TheTvdbClient(
        OnlineMetadataConfig(
            series_provider="thetvdb",
            tvdb_enabled=True,
            tvdb_api_key="api",
            tvdb_bearer_token_store=broken_store,
            cache_enabled=False,
        ),
        cache_dir=tmp_path,
        http_get=fake_get,
        http_post=fake_post,
    )

    assert client.search_series("Test") == []
    assert "konnte nicht dauerhaft gespeichert" in caplog.text


def test_config_from_settings_makes_refreshed_bearer_durable():
    from dragontools.core.online_metadata_config import config_from_settings
    from dragontools.core.settings_metadata import (
        SET_KEY_METADATA_TVDB_API_KEY,
        SET_KEY_METADATA_TVDB_BEARER_TOKEN,
        SET_KEY_METADATA_TVDB_ENABLED,
    )

    settings = DummySettings(
        {
            SET_KEY_METADATA_TVDB_ENABLED: True,
            SET_KEY_METADATA_TVDB_API_KEY: "api",
            SET_KEY_METADATA_TVDB_BEARER_TOKEN: "manual-old",
        }
    )

    config = config_from_settings(settings)
    assert callable(config.tvdb_bearer_token_store)
    config.tvdb_bearer_token_store("auto-new")

    assert settings.values[SET_KEY_METADATA_TVDB_BEARER_TOKEN] == "auto-new"
    assert settings.sync_calls == 1


def test_real_qsettings_config_uses_fresh_store_when_worker_persists(monkeypatch):
    import dragontools.core.online_metadata_config as config_module
    from dragontools.core.settings_metadata import (
        SET_KEY_METADATA_TVDB_API_KEY,
        SET_KEY_METADATA_TVDB_BEARER_TOKEN,
        SET_KEY_METADATA_TVDB_ENABLED,
    )

    FakeQSettings = type("QSettings", (DummySettings,), {})
    FakeQSettings.__module__ = "PyQt6.QtCore"

    original = FakeQSettings(
        {
            SET_KEY_METADATA_TVDB_ENABLED: True,
            SET_KEY_METADATA_TVDB_API_KEY: "api",
            SET_KEY_METADATA_TVDB_BEARER_TOKEN: "old",
        }
    )
    worker_local_store = DummySettings()
    monkeypatch.setattr(config_module, "app_qsettings", lambda: worker_local_store)

    config = config_module.config_from_settings(original)
    assert callable(config.tvdb_bearer_token_store)
    config.tvdb_bearer_token_store("new")

    # The original GUI-thread QSettings object is read-only from the worker's
    # perspective. A fresh application settings instance receives the token.
    assert original.values[SET_KEY_METADATA_TVDB_BEARER_TOKEN] == "old"
    assert worker_local_store.values[SET_KEY_METADATA_TVDB_BEARER_TOKEN] == "new"
    assert worker_local_store.sync_calls == 1


def test_two_clients_from_same_settings_config_reuse_single_refreshed_token(tmp_path):
    from dragontools.core.online_metadata import OnlineMetadataAuthError, TheTvdbClient
    from dragontools.core.online_metadata_config import config_from_settings
    from dragontools.core.settings_metadata import (
        SET_KEY_METADATA_SERIES_PROVIDER,
        SET_KEY_METADATA_TVDB_API_KEY,
        SET_KEY_METADATA_TVDB_BEARER_TOKEN,
        SET_KEY_METADATA_TVDB_ENABLED,
    )

    settings = DummySettings(
        {
            SET_KEY_METADATA_SERIES_PROVIDER: "thetvdb",
            SET_KEY_METADATA_TVDB_ENABLED: True,
            SET_KEY_METADATA_TVDB_API_KEY: "api",
            SET_KEY_METADATA_TVDB_BEARER_TOKEN: "stale-token",
        }
    )
    config = config_from_settings(settings)
    posts = 0

    def fake_post(_url, _headers, _payload, _timeout):
        nonlocal posts
        posts += 1
        return {"data": {"token": "fresh-token"}}

    def fake_get_first(_url, headers, _timeout):
        if headers["Authorization"] == "Bearer stale-token":
            raise OnlineMetadataAuthError("expired")
        assert headers["Authorization"] == "Bearer fresh-token"
        return {"data": []}

    first = TheTvdbClient(
        config,
        cache_dir=tmp_path / "first",
        http_get=fake_get_first,
        http_post=fake_post,
    )
    assert first.search_series("Test") == []
    assert settings.values[SET_KEY_METADATA_TVDB_BEARER_TOKEN] == "fresh-token"

    def fake_get_second(_url, headers, _timeout):
        assert headers["Authorization"] == "Bearer fresh-token"
        return {"data": []}

    second = TheTvdbClient(
        config,
        cache_dir=tmp_path / "second",
        http_get=fake_get_second,
        http_post=lambda *_args: (_ for _ in ()).throw(AssertionError("second login not expected")),
    )
    assert second.search_series("Test") == []
    assert posts == 1


def test_invalid_persisted_bearer_is_cleared_before_refresh(tmp_path):
    from dragontools.core.online_metadata import OnlineMetadataAuthError, TheTvdbClient
    from dragontools.core.online_metadata_config import config_from_settings
    from dragontools.core.settings_metadata import (
        SET_KEY_METADATA_SERIES_PROVIDER,
        SET_KEY_METADATA_TVDB_API_KEY,
        SET_KEY_METADATA_TVDB_BEARER_TOKEN,
        SET_KEY_METADATA_TVDB_ENABLED,
    )

    settings = DummySettings(
        {
            SET_KEY_METADATA_SERIES_PROVIDER: "thetvdb",
            SET_KEY_METADATA_TVDB_ENABLED: True,
            SET_KEY_METADATA_TVDB_API_KEY: "api",
            SET_KEY_METADATA_TVDB_BEARER_TOKEN: "stale-token",
        }
    )
    config = config_from_settings(settings)
    observed_during_login: list[str] = []

    def fake_get(_url, headers, _timeout):
        if headers["Authorization"] == "Bearer stale-token":
            raise OnlineMetadataAuthError("expired")
        return {"data": []}

    def fake_post(_url, _headers, _payload, _timeout):
        observed_during_login.append(settings.values[SET_KEY_METADATA_TVDB_BEARER_TOKEN])
        return {"data": {"token": "fresh-token"}}

    client = TheTvdbClient(
        config,
        cache_dir=tmp_path,
        http_get=fake_get,
        http_post=fake_post,
    )
    assert client.search_series("Test") == []
    assert observed_during_login == [""]
    assert settings.values[SET_KEY_METADATA_TVDB_BEARER_TOKEN] == "fresh-token"
