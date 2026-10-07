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



def test_future_backup_format_is_rejected_without_mutating_settings(tmp_path):
    import json
    import zipfile

    import pytest

    from dragontools.core.settings_backup import inspect_backup, restore_backup

    archive = tmp_path / "future-backup.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps({
            "format": "DragonToolsBackup",
            "format_version": 999,
            "app_version": "99.0",
        }))
        zf.writestr("settings.json", json.dumps({"normal/key": "future"}))

    target = FakeSettings({"keep": "current"})
    with pytest.raises(ValueError, match="neuer als"):
        inspect_backup(archive)
    with pytest.raises(ValueError, match="neuer als"):
        restore_backup(archive, settings=target, documents_dir=tmp_path / "restore")
    assert target.values == {"keep": "current"}


def test_backup_member_limit_is_enforced_before_restore_mutates_settings(tmp_path, monkeypatch):
    import json
    import zipfile

    import pytest

    from dragontools.core import settings_backup_limits as limits
    from dragontools.core.settings_backup import BackupArchiveLimitError, restore_backup

    archive = tmp_path / "too-many-members.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps({
            "format": "DragonToolsBackup", "format_version": 2, "app_version": "9.8.7",
            "secrets": {"mode": "excluded"},
        }))
        zf.writestr("settings.json", "{}")
        zf.writestr("files/rules/a.json", "{}")
        zf.writestr("files/rules/b.json", "{}")

    monkeypatch.setattr(limits, "MAX_BACKUP_MEMBERS", 3)
    target = FakeSettings({"keep": "current"})
    with pytest.raises(BackupArchiveLimitError, match="zu viele ZIP-Einträge"):
        restore_backup(archive, settings=target, documents_dir=tmp_path / "restore")
    assert target.values == {"keep": "current"}


def test_backup_member_size_and_compression_ratio_are_bounded(tmp_path, monkeypatch):
    import json
    import zipfile

    import pytest

    from dragontools.core import settings_backup_limits as limits
    from dragontools.core.settings_backup import BackupArchiveLimitError, inspect_backup

    oversized = tmp_path / "oversized.zip"
    with zipfile.ZipFile(oversized, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps({
            "format": "DragonToolsBackup", "format_version": 2, "app_version": "9.8.7",
            "secrets": {"mode": "excluded"},
        }))
        zf.writestr("settings.json", "x" * 128)
    monkeypatch.setattr(limits, "MAX_BACKUP_MEMBER_BYTES", 64)
    with pytest.raises(BackupArchiveLimitError, match="zu groß"):
        inspect_backup(oversized)

    ratio = tmp_path / "ratio.zip"
    with zipfile.ZipFile(ratio, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps({
            "format": "DragonToolsBackup", "format_version": 2, "app_version": "9.8.7",
            "secrets": {"mode": "excluded"},
        }))
        zf.writestr("settings.json", "A" * 4096)
    monkeypatch.setattr(limits, "MAX_BACKUP_MEMBER_BYTES", 64 * 1024 * 1024)
    monkeypatch.setattr(limits, "COMPRESSION_RATIO_CHECK_MIN_BYTES", 1)
    monkeypatch.setattr(limits, "MAX_BACKUP_COMPRESSION_RATIO", 2.0)
    with pytest.raises(BackupArchiveLimitError, match="Kompressionsverhältnis"):
        inspect_backup(ratio)


def test_unknown_scrypt_profile_is_rejected_before_key_derivation(monkeypatch):
    import base64
    import json

    import pytest

    from dragontools.core import settings_backup_crypto as crypto

    payload = json.dumps({
        "format": "DragonToolsEncryptedSecrets",
        "version": 1,
        "cipher": "AES-256-GCM",
        "kdf": "scrypt",
        "n": 2**20,
        "r": 32,
        "p": 16,
        "salt_b64": base64.b64encode(b"s" * 16).decode("ascii"),
        "nonce_b64": base64.b64encode(b"n" * 12).decode("ascii"),
        "ciphertext_b64": base64.b64encode(b"ciphertext").decode("ascii"),
    }).encode("utf-8")

    def must_not_derive(*_args, **_kwargs):
        raise AssertionError("expensive KDF must not run for unsupported parameters")

    monkeypatch.setattr(crypto, "_derive_key", must_not_derive)
    with pytest.raises(ValueError, match="KDF-Parameter"):
        crypto.decrypt_sensitive_settings(payload, "valid-password")


def test_excluded_backup_preserves_opaque_dpapi_storage_value_verbatim(tmp_path):
    """A local DPAPI blob must never be replaced by an empty decrypted fallback."""
    from dragontools.core.settings import SET_KEY_METADATA_TMDB_API_KEY
    from dragontools.core.settings_backup import export_backup, restore_backup

    archive = tmp_path / "excluded.zip"
    export_backup(
        archive,
        settings=FakeSettings({"normal/key": "from-backup"}),
        documents_dir=tmp_path / "source",
    )

    opaque = "dpapi:v1:not-decryptable-in-this-process"
    target = FakeSettings({
        SET_KEY_METADATA_TMDB_API_KEY: opaque,
        "normal/key": "old",
    })
    restore_backup(
        archive,
        settings=target,
        documents_dir=tmp_path / "restore",
        clear_settings=True,
    )

    assert target.values[SET_KEY_METADATA_TMDB_API_KEY] == opaque
    assert target.values["normal/key"] == "from-backup"


def test_failed_restore_rolls_back_opaque_dpapi_storage_value_verbatim(tmp_path):
    import pytest

    from dragontools.core.settings import SET_KEY_METADATA_TMDB_API_KEY
    from dragontools.core.settings_backup import export_backup, restore_backup

    archive = tmp_path / "restore-fails.zip"
    export_backup(
        archive,
        settings=FakeSettings({"normal/key": "new"}),
        documents_dir=tmp_path / "source",
    )

    opaque = "dpapi:v1:opaque-before-restore"
    target = FailingSyncSettings({
        SET_KEY_METADATA_TMDB_API_KEY: opaque,
        "normal/key": "old",
    })
    with pytest.raises(RuntimeError, match="sync failed"):
        restore_backup(
            archive,
            settings=target,
            documents_dir=tmp_path / "restore",
            clear_settings=True,
        )

    assert target.values == {
        SET_KEY_METADATA_TMDB_API_KEY: opaque,
        "normal/key": "old",
    }


def test_v2_excluded_backup_rejects_plaintext_secret_in_settings_json(tmp_path):
    import json
    import zipfile

    import pytest

    from dragontools.core.settings import SET_KEY_JELLYFIN_API_KEY
    from dragontools.core.settings_backup import restore_backup

    archive = tmp_path / "plaintext-secret.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps({
            "format": "DragonToolsBackup",
            "format_version": 2,
            "app_version": "9.8.7",
            "secrets": {"mode": "excluded"},
        }))
        zf.writestr("settings.json", json.dumps({SET_KEY_JELLYFIN_API_KEY: "must-not-restore"}))

    target = FakeSettings({"keep": "current"})
    with pytest.raises(ValueError, match="sensible Schlüssel im Klartext"):
        restore_backup(archive, settings=target, documents_dir=tmp_path / "restore")
    assert target.values == {"keep": "current"}


def test_encrypted_backup_rejects_non_secret_keys_inside_secret_block(tmp_path):
    import json
    import zipfile

    import pytest

    from dragontools.core.settings_backup import SECRET_MODE_ENCRYPTED, restore_backup
    from dragontools.core.settings_backup_crypto import encrypt_sensitive_settings

    archive = tmp_path / "bad-secret-namespace.zip"
    encrypted = encrypt_sensitive_settings({"normal/key": "override"}, "very-good-password")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps({
            "format": "DragonToolsBackup",
            "format_version": 2,
            "app_version": "9.8.7",
            "secrets": {"mode": SECRET_MODE_ENCRYPTED},
        }))
        zf.writestr("settings.json", json.dumps({"normal/key": "visible"}))
        zf.writestr("secrets.enc", encrypted)

    target = FakeSettings({"keep": "current"})
    with pytest.raises(ValueError, match="nicht-sensitive"):
        restore_backup(
            archive,
            settings=target,
            documents_dir=tmp_path / "restore",
            password="very-good-password",
        )
    assert target.values == {"keep": "current"}


def test_restore_rejects_unexpected_or_nested_backup_file_members(tmp_path):
    import json
    import zipfile

    import pytest

    from dragontools.core.settings_backup import restore_backup

    for member in (
        "files/rules/nested/audio_rules.json",
        "files/profiles/not-a-profile.json",
        "files/unknown/data.json",
    ):
        archive = tmp_path / (member.replace("/", "_") + ".zip")
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps({
                "format": "DragonToolsBackup",
                "format_version": 2,
                "app_version": "9.8.7",
                "secrets": {"mode": "excluded"},
            }))
            zf.writestr("settings.json", "{}")
            zf.writestr(member, "{}")
        target = FakeSettings({"keep": "current"})
        with pytest.raises(ValueError, match="Backup|Backup|Eintrag"):
            restore_backup(archive, settings=target, documents_dir=tmp_path / "restore")
        assert target.values == {"keep": "current"}


def test_restore_rejects_invalid_serialized_bytes_without_mutating_settings(tmp_path):
    import json
    import zipfile

    import pytest

    from dragontools.core.settings_backup import restore_backup

    archive = tmp_path / "invalid-bytes.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps({
            "format": "DragonToolsBackup",
            "format_version": 2,
            "app_version": "9.8.7",
            "secrets": {"mode": "excluded"},
        }))
        zf.writestr("settings.json", json.dumps({
            "ui/geometry": {"__bytes_b64__": "%%%not-base64%%%"},
        }))

    target = FakeSettings({"keep": "current"})
    with pytest.raises(ValueError, match="Base64"):
        restore_backup(archive, settings=target, documents_dir=tmp_path / "restore")
    assert target.values == {"keep": "current"}


def test_atomic_restore_write_fsyncs_staged_file(tmp_path, monkeypatch):
    from dragontools.core import settings_backup_restore as module

    calls: list[int] = []
    real_fsync = module.os.fsync

    def capture_fsync(fd: int):
        calls.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr(module.os, "fsync", capture_fsync)
    target = tmp_path / "rules" / "audio_rules.json"
    target.parent.mkdir(parents=True)

    module.atomic_write_bytes(target, b'{"safe": true}')

    assert target.read_bytes() == b'{"safe": true}'
    assert calls, "Restore-Dateien müssen vor os.replace() fsync erhalten."


def test_encrypted_backup_fails_instead_of_exporting_empty_unreadable_dpapi_secret(tmp_path):
    import pytest

    from dragontools.core.secret_settings import SecretProtectionError
    from dragontools.core.settings import SET_KEY_METADATA_TMDB_API_KEY
    from dragontools.core.settings_backup import SECRET_MODE_ENCRYPTED, export_backup

    target = tmp_path / "must-not-exist.zip"
    settings = FakeSettings({
        "normal/key": "visible",
        SET_KEY_METADATA_TMDB_API_KEY: "dpapi:v1:opaque-from-other-user",
    })

    with pytest.raises(SecretProtectionError, match="verschlüsselte Backup"):
        export_backup(
            target,
            settings=settings,
            documents_dir=tmp_path / "source",
            secret_mode=SECRET_MODE_ENCRYPTED,
            password="strong-password",
        )

    assert not target.exists()
