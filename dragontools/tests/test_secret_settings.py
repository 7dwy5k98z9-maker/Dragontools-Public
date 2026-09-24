from __future__ import annotations

from dragontools.core import secret_settings


class FakeSettings:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def value(self, key, default=None, *, type=None):
        value = self.values.get(key, default)
        return type(value) if type is not None and value is not None else value

    def setValue(self, key, value):
        self.values[key] = value


def test_legacy_plaintext_secret_remains_readable():
    settings = FakeSettings({"secret": "legacy"})
    assert secret_settings.read_secret(settings, "secret") == "legacy"


def test_fake_non_qsettings_store_keeps_test_and_cross_platform_behavior():
    settings = FakeSettings()
    secret_settings.write_secret(settings, "secret", "value")
    assert settings.values["secret"] == "value"


def test_protected_value_roundtrip_uses_dpapi_helpers(monkeypatch):
    monkeypatch.setattr(secret_settings, "_dpapi_protect", lambda value: "dpapi:v1:encoded-" + value)
    monkeypatch.setattr(secret_settings, "_dpapi_unprotect", lambda value: value.removeprefix("dpapi:v1:encoded-"))
    stored = secret_settings.protect_secret_for_storage("token", enabled=True)
    assert secret_settings.is_protected_secret_value(stored)
    assert secret_settings.decode_secret_from_storage(stored) == "token"


def test_corrupt_protected_secret_fails_closed(monkeypatch):
    settings = FakeSettings({"secret": "dpapi:v1:broken"})
    monkeypatch.setattr(
        secret_settings,
        "_dpapi_unprotect",
        lambda _value: (_ for _ in ()).throw(secret_settings.SecretProtectionError("broken")),
    )
    assert secret_settings.read_secret(settings, "secret", "") == ""


def test_real_qsettings_policy_protects_before_persisting(monkeypatch):
    settings = FakeSettings()
    monkeypatch.setattr(secret_settings.os, "name", "nt")
    monkeypatch.setattr(secret_settings, "_is_real_qsettings", lambda _settings: True)
    monkeypatch.setattr(secret_settings, "_dpapi_protect", lambda value: "dpapi:v1:" + value)

    secret_settings.write_secret(settings, "secret", "token")

    assert settings.values["secret"] == "dpapi:v1:token"
