from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest


def test_quarantine_corrupt_file_moves_original_and_preserves_payload(tmp_path):
    from dragontools.core.json_io import quarantine_corrupt_file

    source = tmp_path / "rules.json"
    payload = "{not valid json"
    source.write_text(payload, encoding="utf-8")

    backup = quarantine_corrupt_file(source)

    assert backup is not None
    assert not source.exists()
    assert backup.exists()
    assert backup.parent == source.parent
    assert backup.name.startswith("rules.corrupt_")
    assert backup.suffix == ".json"
    assert backup.read_text(encoding="utf-8") == payload


def test_profile_manager_quarantines_broken_json_and_reports_warning(tmp_path):
    from dragontools.core.profile_manager import ProfileManager

    source = tmp_path / "h265_profiles.json"
    payload = "{broken"
    source.write_text(payload, encoding="utf-8")
    reports: list[tuple] = []

    manager = ProfileManager(source, reporter=lambda *args: reports.append(args))

    backups = list(tmp_path.glob("h265_profiles.corrupt_*.json"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == payload
    assert not source.exists()
    assert reports
    assert any("gesichert" in str(args[0]) for args in reports)
    # Built-ins bleiben trotz defekter Userdatei verfuegbar.
    assert manager.get("film_cpu")["codec"] == "h265"


def test_profile_manager_quarantines_non_object_json_instead_of_overwriting_it(tmp_path):
    from dragontools.core.profile_manager import ProfileManager

    source = tmp_path / "h265_profiles.json"
    payload = json.dumps([{"unexpected": True}])
    source.write_text(payload, encoding="utf-8")

    ProfileManager(source)

    backups = list(tmp_path.glob("h265_profiles.corrupt_*.json"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == payload
    assert not source.exists()


def test_profile_manager_does_not_swallow_migration_programming_errors(tmp_path, monkeypatch):
    import dragontools.core.profile_manager as profile_manager

    source = tmp_path / "h265_profiles.json"
    source.write_text(json.dumps({"_schema_version": 3}), encoding="utf-8")

    def explode(*_args, **_kwargs):
        raise RuntimeError("migration bug")

    monkeypatch.setattr(profile_manager, "migrate_profile_collection", explode)

    with pytest.raises(RuntimeError, match="migration bug"):
        profile_manager.ProfileManager(source)

    # Ein Programmierfehler ist keine Dateikorruption: Original nicht wegverschieben.
    assert source.exists()
    assert not list(tmp_path.glob("h265_profiles.corrupt_*.json"))


def test_user_rule_loader_quarantines_broken_json_before_migration_write(tmp_path, monkeypatch):
    import dragontools.rules.rule_loader as loader

    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    source = rules_dir / "subtitle_rules.json"
    payload = "{broken subtitle rules"
    source.write_text(payload, encoding="utf-8")
    reports: list[tuple] = []

    monkeypatch.setattr(loader, "_rules_dir", lambda: rules_dir)

    result = loader.load_named_rules(
        "subtitle_rules",
        default={"fallback": True},
        reporter=lambda *args: reports.append(args),
        migrator=lambda data: {**data, "migrated": True},
    )

    backups = list(rules_dir.glob("subtitle_rules.corrupt_*.json"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == payload
    assert source.exists(), "Migration darf nach der Sicherung eine frische valide Datei anlegen."
    saved = json.loads(source.read_text(encoding="utf-8"))
    assert saved == {"fallback": True, "migrated": True}
    assert result == saved
    assert any("gesichert" in str(args[0]) for args in reports)


def test_user_rule_loader_quarantines_non_object_json(tmp_path, monkeypatch):
    import dragontools.rules.rule_loader as loader

    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    source = rules_dir / "move_rules.json"
    payload = json.dumps(["invalid", "shape"])
    source.write_text(payload, encoding="utf-8")

    monkeypatch.setattr(loader, "_rules_dir", lambda: rules_dir)

    result = loader.load_named_rules(
        "move_rules",
        default={"fallback": 1},
        migrator=lambda data: {**data, "migrated": 1},
    )

    backups = list(rules_dir.glob("move_rules.corrupt_*.json"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == payload
    assert result == {"fallback": 1, "migrated": 1}
    assert json.loads(source.read_text(encoding="utf-8")) == result


def test_media_library_series_parse_failure_is_logged_instead_of_silently_swallowed(
    tmp_path, monkeypatch, caplog
):
    import dragontools.rules.move_rules as move_rules
    from dragontools.core.media_library_repository import _fallback_item_from_path

    def explode(_path):
        raise RuntimeError("parser bug")

    monkeypatch.setattr(move_rules, "parse_series_match_details", explode)
    path = tmp_path / "Serie - S01E01 - Folge.mkv"

    with caplog.at_level(logging.WARNING):
        item = _fallback_item_from_path(path)

    assert item["path"] == str(path)
    assert "Serienmetadaten konnten" in caplog.text
    assert "parser bug" in caplog.text
