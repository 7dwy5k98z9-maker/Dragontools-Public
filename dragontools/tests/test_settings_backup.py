from __future__ import annotations


class FakeSettings:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.synced = False

    def allKeys(self):
        return list(self.values.keys())

    def value(self, key):
        return self.values.get(key)

    def setValue(self, key, value):
        self.values[key] = value

    def clear(self):
        self.values.clear()

    def sync(self):
        self.synced = True


class FailingSyncSettings(FakeSettings):
    def sync(self):
        raise RuntimeError("sync failed")


def test_backup_exports_and_restores_settings_rules_and_profiles(tmp_path):
    from dragontools.core.settings_backup import export_backup, restore_backup

    source_root = tmp_path / "source"
    restore_root = tmp_path / "restore"
    (source_root / "rules").mkdir(parents=True)
    (source_root / "rules" / "audio_rules.json").write_text('{"audio": true}', encoding="utf-8")
    (source_root / "h265_profiles.json").write_text('{"film": {"crf": 23}}', encoding="utf-8")

    archive = tmp_path / "backup.zip"
    export_backup(
        archive,
        settings=FakeSettings({"tools/ffmpeg/dir": "C:/Tools/FFmpeg", "tabs/visible/h265": True}),
        documents_dir=source_root,
    )

    restored_settings = FakeSettings({"old": "value"})
    result = restore_backup(
        archive,
        settings=restored_settings,
        documents_dir=restore_root,
        clear_settings=True,
    )

    assert restored_settings.values["tools/ffmpeg/dir"] == "C:/Tools/FFmpeg"
    assert restored_settings.values["tabs/visible/h265"] is True
    assert "old" not in restored_settings.values
    assert (restore_root / "rules" / "audio_rules.json").read_text(encoding="utf-8") == '{"audio": true}'
    assert (restore_root / "h265_profiles.json").read_text(encoding="utf-8") == '{"film": {"crf": 23}}'
    assert result["manifest"]["format"] == "DragonToolsBackup"
    assert restored_settings.synced is True


def test_settings_to_dict_can_mask_sensitive_online_metadata_values():
    from dragontools.core.settings import (
        SET_KEY_METADATA_TMDB_API_KEY,
        SET_KEY_METADATA_TMDB_READ_TOKEN,
    )
    from dragontools.core.settings_backup import settings_to_dict

    settings = FakeSettings({
        "normal/key": "visible",
        SET_KEY_METADATA_TMDB_API_KEY: "tmdb-api-secret",
        SET_KEY_METADATA_TMDB_READ_TOKEN: "tmdb-read-token-secret",
    })

    masked = settings_to_dict(settings, mask_sensitive=True)
    raw = settings_to_dict(settings)

    assert masked["normal/key"] == "visible"
    assert masked[SET_KEY_METADATA_TMDB_API_KEY] == "********"
    assert masked[SET_KEY_METADATA_TMDB_READ_TOKEN] == "********"
    assert raw[SET_KEY_METADATA_TMDB_API_KEY] == "tmdb-api-secret"
    assert raw[SET_KEY_METADATA_TMDB_READ_TOKEN] == "tmdb-read-token-secret"



def test_default_backup_omits_sensitive_values_and_preserves_local_secrets_on_restore(tmp_path):
    import json
    import zipfile

    from dragontools.core.settings import SET_KEY_METADATA_TMDB_API_KEY
    from dragontools.core.settings_backup import export_backup, restore_backup

    archive = tmp_path / "safe-backup.zip"
    export_backup(
        archive,
        settings=FakeSettings({
            "normal/key": "from-backup",
            SET_KEY_METADATA_TMDB_API_KEY: "must-not-be-plaintext",
        }),
        documents_dir=tmp_path / "source",
    )

    with zipfile.ZipFile(archive, "r") as zf:
        settings_data = json.loads(zf.read("settings.json").decode("utf-8"))
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert SET_KEY_METADATA_TMDB_API_KEY not in settings_data
        assert "secrets.enc" not in zf.namelist()
        assert manifest["secrets"]["mode"] == "excluded"

    target = FakeSettings({SET_KEY_METADATA_TMDB_API_KEY: "local-secret", "old": "gone"})
    result = restore_backup(archive, settings=target, documents_dir=tmp_path / "restore", clear_settings=True)

    assert target.values["normal/key"] == "from-backup"
    assert target.values[SET_KEY_METADATA_TMDB_API_KEY] == "local-secret"
    assert "old" not in target.values
    assert result["secret_mode"] == "excluded"


def test_encrypted_backup_roundtrip_and_wrong_password_is_non_destructive(tmp_path):
    import json
    import zipfile

    import pytest

    from dragontools.core.settings import (
        SET_KEY_METADATA_TMDB_API_KEY,
        SET_KEY_METADATA_TVDB_PIN,
    )
    from dragontools.core.settings_backup import (
        InvalidBackupPassword,
        SECRET_MODE_ENCRYPTED,
        export_backup,
        inspect_backup,
        restore_backup,
    )

    archive = tmp_path / "encrypted-backup.zip"
    export_backup(
        archive,
        settings=FakeSettings({
            "normal/key": "visible",
            SET_KEY_METADATA_TMDB_API_KEY: "tmdb-secret-123",
            SET_KEY_METADATA_TVDB_PIN: "tvdb-pin-456",
        }),
        documents_dir=tmp_path / "source",
        secret_mode=SECRET_MODE_ENCRYPTED,
        password="very-good-password",
    )

    info = inspect_backup(archive)
    assert info["requires_password"] is True
    assert info["secret_mode"] == SECRET_MODE_ENCRYPTED

    with zipfile.ZipFile(archive, "r") as zf:
        normal = json.loads(zf.read("settings.json").decode("utf-8"))
        encrypted_payload = zf.read("secrets.enc")
        assert SET_KEY_METADATA_TMDB_API_KEY not in normal
        assert b"tmdb-secret-123" not in encrypted_payload
        assert b"tvdb-pin-456" not in encrypted_payload

    unchanged = FakeSettings({"keep": "current"})
    with pytest.raises(InvalidBackupPassword):
        restore_backup(
            archive,
            settings=unchanged,
            documents_dir=tmp_path / "wrong",
            clear_settings=True,
            password="wrong-password",
        )
    assert unchanged.values == {"keep": "current"}

    restored = FakeSettings({"old": "gone"})
    result = restore_backup(
        archive,
        settings=restored,
        documents_dir=tmp_path / "restore",
        clear_settings=True,
        password="very-good-password",
    )
    assert restored.values["normal/key"] == "visible"
    assert restored.values[SET_KEY_METADATA_TMDB_API_KEY] == "tmdb-secret-123"
    assert restored.values[SET_KEY_METADATA_TVDB_PIN] == "tvdb-pin-456"
    assert "old" not in restored.values
    assert result["secret_mode"] == SECRET_MODE_ENCRYPTED


def test_encrypted_backup_requires_password(tmp_path):
    import pytest

    from dragontools.core.settings_backup import (
        BackupPasswordRequired,
        SECRET_MODE_ENCRYPTED,
        export_backup,
    )

    with pytest.raises(BackupPasswordRequired):
        export_backup(
            tmp_path / "backup.zip",
            settings=FakeSettings({"normal/key": "value"}),
            documents_dir=tmp_path / "source",
            secret_mode=SECRET_MODE_ENCRYPTED,
        )


def test_legacy_v1_plaintext_backup_remains_restore_compatible(tmp_path):
    import json
    import zipfile

    from dragontools.core.settings import SET_KEY_METADATA_TMDB_API_KEY
    from dragontools.core.settings_backup import restore_backup

    archive = tmp_path / "legacy-v1.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps({
            "format": "DragonToolsBackup",
            "format_version": 1,
            "app_version": "9.5",
        }))
        zf.writestr("settings.json", json.dumps({
            "normal/key": "legacy",
            SET_KEY_METADATA_TMDB_API_KEY: "legacy-secret",
        }))

    restored = FakeSettings({"old": "gone"})
    result = restore_backup(
        archive,
        settings=restored,
        documents_dir=tmp_path / "restore",
        clear_settings=True,
    )

    assert restored.values["normal/key"] == "legacy"
    assert restored.values[SET_KEY_METADATA_TMDB_API_KEY] == "legacy-secret"
    assert result["secret_mode"] == "legacy_plaintext"


def test_legacy_v1_restore_can_keep_local_plaintext_secrets(tmp_path):
    import json
    import zipfile

    from dragontools.core.settings import SET_KEY_METADATA_TMDB_API_KEY
    from dragontools.core.settings_backup import inspect_backup, restore_backup

    archive = tmp_path / "legacy-v1.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps({
            "format": "DragonToolsBackup",
            "format_version": 1,
            "app_version": "9.5",
        }))
        zf.writestr("settings.json", json.dumps({
            "normal/key": "legacy",
            SET_KEY_METADATA_TMDB_API_KEY: "legacy-secret",
        }))

    info = inspect_backup(archive)
    assert info["secret_mode"] == "legacy_plaintext"

    restored = FakeSettings({
        SET_KEY_METADATA_TMDB_API_KEY: "local-secret",
        "old": "gone",
    })
    result = restore_backup(
        archive,
        settings=restored,
        documents_dir=tmp_path / "restore",
        clear_settings=True,
        restore_legacy_plaintext_secrets=False,
    )

    assert restored.values["normal/key"] == "legacy"
    assert restored.values[SET_KEY_METADATA_TMDB_API_KEY] == "local-secret"
    assert "old" not in restored.values
    assert result["secret_mode"] == "legacy_plaintext"
    assert result["legacy_plaintext_secrets_restored"] is False


def test_restore_backup_rolls_back_settings_and_files_on_error(tmp_path):
    import pytest

    from dragontools.core.settings_backup import export_backup, restore_backup

    source_root = tmp_path / "source"
    restore_root = tmp_path / "restore"
    (source_root / "rules").mkdir(parents=True)
    (source_root / "rules" / "audio_rules.json").write_text('{"new": true}', encoding="utf-8")
    (restore_root / "rules").mkdir(parents=True)
    (restore_root / "rules" / "audio_rules.json").write_text('{"old": true}', encoding="utf-8")

    archive = tmp_path / "backup.zip"
    export_backup(
        archive,
        settings=FakeSettings({"normal/key": "from-backup"}),
        documents_dir=source_root,
    )

    target = FailingSyncSettings({"normal/key": "old-value", "keep": "yes"})
    with pytest.raises(RuntimeError):
        restore_backup(
            archive,
            settings=target,
            documents_dir=restore_root,
            clear_settings=True,
        )

    assert target.values == {"normal/key": "old-value", "keep": "yes"}
    assert (restore_root / "rules" / "audio_rules.json").read_text(encoding="utf-8") == '{"old": true}'
