from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_release_manifest_matches_985() -> None:
    from dragontools.core.version import APP_VERSION

    manifest = json.loads((ROOT / "release_manifest.json").read_text(encoding="utf-8"))
    assert APP_VERSION == "9.8.6"
    assert manifest["app_version"] == APP_VERSION
    assert "9.8.6" in manifest["help_policy"]


def test_whisper_is_declared_and_build_script_auto_installs_and_collects_it() -> None:
    optional = (ROOT / "requirements-optional.txt").read_text(encoding="utf-8").casefold()
    whisper = (ROOT / "requirements-whisper.txt").read_text(encoding="utf-8").casefold()
    build = (ROOT / "build_v9.bat").read_text(encoding="utf-8").casefold()

    assert "requirements-whisper.txt" in optional
    assert "faster-whisper" in whisper
    assert "ctranslate2" in whisper
    assert 'import faster_whisper, ctranslate2' in build
    assert "pip install -r requirements-whisper.txt" in build
    assert "--collect-all faster_whisper" in build
    assert "--collect-all ctranslate2" in build
    assert "--copy-metadata faster-whisper" in build


def test_patch_documented_product_modules_are_all_release_smoke_covered() -> None:
    from dragontools.core.release_validation_package import _SMOKE_MODULES

    text = (ROOT / "PATCH.md").read_text(encoding="utf-8")
    documented = {
        match.group(1).replace("\\", "/")
        for match in re.finditer(
            r"`(?:dragontools/)?((?:core|gui|worker|rules|subtitle)/[^`\s]+?\.py)`",
            text,
        )
    }
    covered = {path.as_posix() for path in _SMOKE_MODULES}
    assert documented <= covered, sorted(documented - covered)
    assert "gui/online_metadata_action_workers.py" in covered


def test_future_rule_schema_is_rejected_instead_of_downgraded() -> None:
    from dragontools.core.config_migration import UnsupportedConfigSchemaError
    from dragontools.rules.audio_rules import migrate_audio_rules

    with pytest.raises(UnsupportedConfigSchemaError, match=r"Schema 99.*Schema 4"):
        migrate_audio_rules({"_schema_version": 99, "future": {"keep": True}})


def test_rule_loader_preserves_future_user_file_and_uses_defaults(tmp_path, monkeypatch) -> None:
    from dragontools.rules import rule_loader
    from dragontools.rules.audio_rules import migrate_audio_rules

    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    source = rules_dir / "audio_rules.json"
    payload = {"_schema_version": 99, "future": {"keep": True}}
    source.write_text(json.dumps(payload), encoding="utf-8")
    warnings: list[str] = []

    monkeypatch.setattr(rule_loader, "_rules_dir", lambda: rules_dir)
    loaded = rule_loader.load_named_rules(
        "audio_rules",
        default={"safe": True},
        migrator=migrate_audio_rules,
        reporter=lambda message, *_args: warnings.append(str(message)),
    )

    assert loaded == {"safe": True}
    assert json.loads(source.read_text(encoding="utf-8")) == payload
    assert any("neueres Schema" in message for message in warnings)


def test_metadata_retry_after_is_capped(monkeypatch) -> None:
    import dragontools.core.online_metadata_retry as retry

    delays: list[float] = []
    calls = 0
    monkeypatch.setattr(retry.time, "sleep", delays.append)
    monkeypatch.setattr(retry.random, "uniform", lambda _start, _end: 0.0)

    def operation():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise retry.RetryableOnlineMetadataError("429", retry_after=3600.0)
        return "ok"

    assert retry.retry_online_metadata_call(operation, provider="Test") == "ok"
    assert delays == [retry.MAX_RETRY_AFTER_S]


def test_jellyfin_retry_after_is_capped() -> None:
    from dragontools.core.jellyfin_api import JellyfinClient, _MAX_RETRY_AFTER_SECONDS

    sleeps: list[float] = []
    client = JellyfinClient("http://localhost", "key", sleeper=sleeps.append)
    client._sleep_before_retry(1, retry_after=3600.0)
    assert sleeps == [_MAX_RETRY_AFTER_SECONDS]

def test_build_script_enforces_source_free_bundle_without_requiring_python_sources() -> None:
    build = (ROOT / "build_v9.bat").read_text(encoding="utf-8").casefold()

    assert '--add-data "dragontools;python\\dragontools"' not in build
    assert '--add-data "dragontoolsv9.py;python"' not in build
    assert '"%data_root%\\python\\dragontools\\__init__.py"' not in build
    assert '"%data_root%\\python\\dragontoolsv9.py"' not in build
    assert 'if exist "%data_root%\\python"' in build



def test_profile_manager_blocks_future_schema_on_later_write(tmp_path) -> None:
    from dragontools.core.config_migration import UnsupportedConfigSchemaError
    from dragontools.core.profile_manager import ProfileManager

    source = tmp_path / "h265_profiles.json"
    payload = {
        "_schema_version": 99,
        "future_profile": {"label": "Future", "codec": "h265", "future_only": True},
    }
    source.write_text(json.dumps(payload), encoding="utf-8")

    manager = ProfileManager(source)
    assert json.loads(source.read_text(encoding="utf-8")) == payload

    with pytest.raises(UnsupportedConfigSchemaError, match=r"Schema 99.*Schema 3"):
        manager.set("new_profile", {"label": "Neu", "codec": "h265"})

    assert json.loads(source.read_text(encoding="utf-8")) == payload
    assert "new_profile" not in manager._user


def test_rule_storage_blocks_future_schema_on_later_write(tmp_path, monkeypatch) -> None:
    from dragontools.core.config_migration import UnsupportedConfigSchemaError
    from dragontools.gui import rules_dialog_storage as storage

    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    source = rules_dir / "audio_rules.json"
    payload = {
        "_schema_version": 99,
        "future_only": {"keep": True},
        "rules": {"keep_me": True},
    }
    source.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(storage, "_rules_dir", lambda: rules_dir)

    with pytest.raises(UnsupportedConfigSchemaError, match=r"Schema 99.*Schema 4"):
        storage._save("audio_rules", {"_schema_version": 4, "rules": {"changed": True}})

    assert json.loads(source.read_text(encoding="utf-8")) == payload


def test_write_guard_rechecks_file_changed_after_load(tmp_path) -> None:
    from dragontools.core.config_migration import UnsupportedConfigSchemaError
    from dragontools.core.profile_manager import ProfileManager

    source = tmp_path / "h265_profiles.json"
    source.write_text(json.dumps({"_schema_version": 3}), encoding="utf-8")
    manager = ProfileManager(source)

    future = {"_schema_version": 77, "external_future_data": {"keep": True}}
    source.write_text(json.dumps(future), encoding="utf-8")

    with pytest.raises(UnsupportedConfigSchemaError, match=r"Schema 77.*Schema 3"):
        manager.save()
    assert json.loads(source.read_text(encoding="utf-8")) == future


def test_whisper_build_uses_dedicated_versioned_requirements() -> None:
    whisper = (ROOT / "requirements-whisper.txt").read_text(encoding="utf-8").casefold().replace(" ", "")
    optional = (ROOT / "requirements-optional.txt").read_text(encoding="utf-8").casefold().replace(" ", "")
    build = (ROOT / "build_v9.bat").read_text(encoding="utf-8").casefold()

    assert "faster-whisper>=1.1,<2" in whisper
    assert "ctranslate2>=4.4,<5" in whisper
    assert "-rrequirements-whisper.txt" in optional
    assert "pip install -r requirements-whisper.txt" in build
    assert "pip install -r requirements-optional.txt" not in build
    assert "from importlib.metadata import version" in build
