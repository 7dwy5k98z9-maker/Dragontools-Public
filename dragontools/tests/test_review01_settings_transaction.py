from __future__ import annotations

import ast
from pathlib import Path

import pytest


class FakeSettings:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.synced = 0

    def allKeys(self):
        return list(self.values)

    def value(self, key, default=None, **_kwargs):
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.values[key] = value

    def clear(self):
        self.values.clear()

    def sync(self):
        self.synced += 1


def test_settings_transaction_rolls_back_all_earlier_sections_on_validation_failure():
    from dragontools.core.settings_access import save_settings_transaction

    opaque = "dpapi:v1:opaque"
    settings = FakeSettings({"first": "old", "jellyfin_api/api_key": opaque})

    def first_section():
        settings.setValue("first", "new")
        settings.setValue("created", "temporary")
        return True

    def later_invalid_section():
        settings.setValue("second", "would-be-partial")
        return False

    assert save_settings_transaction(settings, (first_section, later_invalid_section)) is False
    assert settings.values == {"first": "old", "jellyfin_api/api_key": opaque}


def test_settings_transaction_rolls_back_on_exception_and_preserves_raw_secret():
    from dragontools.core.settings_access import save_settings_transaction

    opaque = "dpapi:v1:opaque-ciphertext"
    settings = FakeSettings({"normal": "old", "metadata/tmdb/api_key": opaque})

    def writer():
        settings.setValue("normal", "new")
        settings.setValue("metadata/tmdb/api_key", "changed")
        raise OSError("disk failure")

    with pytest.raises(OSError, match="disk failure"):
        save_settings_transaction(settings, (writer,))

    assert settings.values == {"normal": "old", "metadata/tmdb/api_key": opaque}


def test_settings_dialog_uses_transactional_save_helper():
    source = (
        Path(__file__).resolve().parents[1] / "gui" / "settings_dialog.py"
    ).read_text(encoding="utf-8")
    assert "save_settings_transaction" in source
    assert "(section.save for section in self._active_sections())" in source
    assert "for section in self._active_sections():\n            section.build(layout)" in source


def test_timeout_seconds_to_minutes_really_rounds_up_without_importing_qt():
    source_path = Path(__file__).resolve().parents[1] / "gui" / "timeout_settings_dialog.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_s_to_min"
    )
    module = ast.Module(body=[function], type_ignores=[])
    namespace: dict[str, object] = {}
    exec(compile(ast.fix_missing_locations(module), str(source_path), "exec"), namespace)
    convert = namespace["_s_to_min"]

    assert convert(60) == 1
    assert convert(61) == 2
    assert convert(90) == 2
    assert convert(119) == 2
    assert convert(120) == 2


def test_logging_settings_ui_describes_base_directory_semantics():
    source = (
        Path(__file__).resolve().parents[1] / "gui" / "settings_sections" / "storage.py"
    ).read_text(encoding="utf-8")
    assert '"Log-Basisordner:"' in source
    assert "DragonTools hängt automatisch 'Logging/Jahr/Monat' an" in source
    assert "Leer = Dokumente/DragonTools/Logging" not in source


def test_profile_manager_returns_detached_nested_profile_data(tmp_path):
    from dragontools.core.profile_manager import ProfileManager

    manager = ProfileManager(tmp_path / "h265_profiles.json")
    original_bf = manager.get("film_cpu")["encoder_options"]["bf"]

    first = manager.get("film_cpu")
    first["encoder_options"]["bf"] = 999
    assert manager.get("film_cpu")["encoder_options"]["bf"] == original_bf

    data = manager.data
    data["film_cpu"]["encoder_options"]["bf"] = 777
    assert manager.get("film_cpu")["encoder_options"]["bf"] == original_bf


def test_focused_settings_dialog_saves_only_owner_sections():
    source = (
        Path(__file__).resolve().parents[1] / "gui" / "settings_dialog.py"
    ).read_text(encoding="utf-8")
    assert "def _active_sections(self):" in source
    assert "visible.intersection(section.section_keys)" in source
    assert "(section.save for section in self._active_sections())" in source
    assert "for section in self._active_sections():\n            section.build(layout)" in source


def test_jellyfin_settings_preserve_unreadable_dpapi_blob_until_explicit_edit():
    source = (
        Path(__file__).resolve().parents[1] / "gui" / "settings_sections" / "jellyfin.py"
    ).read_text(encoding="utf-8")
    assert "read_secret_state" in source
    assert "self._api_key_was_unreadable" in source
    assert "self._api_key_user_edited" in source
    assert "if not preserve_unreadable_api_key:" in source


def test_profile_dialogs_surface_filesystem_save_failures_instead_of_claiming_success():
    gui_root = Path(__file__).resolve().parents[1] / "gui"
    manager = (gui_root / "profile_manager_dialog.py").read_text(encoding="utf-8")
    service = (gui_root / "encoder_profile_service.py").read_text(encoding="utf-8")
    assert "except OSError as exc:" in manager
    assert '"Profil nicht gelöscht"' in manager
    assert "except OSError as exc:" in service
    assert '"Profil nicht gespeichert"' in service


def test_storage_section_validates_all_paths_before_persisting_any_path():
    path = Path(__file__).resolve().parents[1] / "gui" / "settings_sections" / "storage.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "StorageLoggingSection")
    save = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "save")
    text = ast.get_source_segment(source, save) or ""
    assert "resolved_paths" in text
    assert text.index("resolved_paths[key] = value") < text.index("s.setValue(key, value)")


def test_timeout_migration_is_idempotent_and_marks_only_successful_transaction(monkeypatch):
    from dragontools.core import timeout_settings as module

    settings = FakeSettings({
        "timeouts/encoder_general": 7200,
        "timeouts/dv_encode": 4000,
    })
    monkeypatch.setattr(module, "_read_qsettings_or_none", lambda: settings)
    calls = []

    def run_transaction(mutator):
        calls.append(1)
        mutator(settings)

    monkeypatch.setattr(module, "_write_qsettings_transaction", run_transaction)

    module.migrate_v91_timeout_defaults()
    assert settings.values["timeouts/encoder_general"] == module._BY_KEY["encoder_general"].default_s
    assert settings.values["timeouts/dv_encode"] == module._BY_KEY["dv_encode"].default_s
    assert settings.values["timeouts/v91_inactivity_migrated"] is True
    assert len(calls) == 1

    module.migrate_v91_timeout_defaults()
    assert len(calls) == 1


def test_timeout_migration_storage_failure_does_not_claim_completion(monkeypatch):
    from dragontools.core import timeout_settings as module

    settings = FakeSettings({"timeouts/encoder_general": 7200})
    monkeypatch.setattr(module, "_read_qsettings_or_none", lambda: settings)
    monkeypatch.setattr(
        module,
        "_write_qsettings_transaction",
        lambda _mutator: (_ for _ in ()).throw(OSError("registry read-only")),
    )

    module.migrate_v91_timeout_defaults()

    assert "timeouts/v91_inactivity_migrated" not in settings.values
