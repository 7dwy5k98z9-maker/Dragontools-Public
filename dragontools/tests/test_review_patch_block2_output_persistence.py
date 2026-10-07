# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path


def test_auxiliary_overwrite_workers_use_central_commit_service():
    project = Path(__file__).resolve().parents[1]
    for rel in (
        "worker/dv_remux_components.py",
        "worker/mp4_remux_file_service.py",
        "worker/audio_mux_thread.py",
    ):
        text = (project / rel).read_text(encoding="utf-8")
        assert "commit_staged_output" in text, rel
        assert "os.replace(" not in text, rel

    thread_text = (project / "worker/mp4_remux_thread.py").read_text(encoding="utf-8")
    assert "commit_staged_output" not in thread_text
    assert "MP4RemuxFileService" in thread_text


def test_rules_dialog_storage_uses_atomic_json_writer(tmp_path, monkeypatch):
    from dragontools.gui import rules_dialog_storage as storage

    captured: list[tuple[Path, dict]] = []
    monkeypatch.setattr(storage, "_rules_dir", lambda: tmp_path)
    monkeypatch.setattr(
        storage,
        "write_json_atomic",
        lambda path, data: captured.append((Path(path), dict(data))),
    )
    monkeypatch.setattr(storage, "append_audit_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(storage._ar, "reload_rules", lambda: None)
    monkeypatch.setattr(storage._rr, "reload_rules", lambda: None)

    storage._save("subtitle_rules", {"mp4_sidecars_enabled": False})

    assert len(captured) == 1
    path, payload = captured[0]
    assert path == tmp_path / "subtitle_rules.json"
    assert payload["mp4_sidecars_enabled"] is False
    assert payload["_schema_version"] == 7


def test_profile_manager_save_uses_atomic_json_writer(tmp_path, monkeypatch):
    from dragontools.core import profile_manager as module

    captured: list[tuple[Path, dict]] = []
    monkeypatch.setattr(
        module,
        "write_json_atomic",
        lambda path, data: captured.append((Path(path), dict(data))),
    )

    path = tmp_path / "h265_profiles.json"
    manager = module.ProfileManager(path)
    manager._user = {
        "mein_profil": {
            "label": "Mein Profil",
            "codec": "h265",
            "encoder_options": {"encoder": "cpu"},
        }
    }
    manager.save()

    assert len(captured) == 1
    written_path, payload = captured[0]
    assert written_path == path
    assert payload["_schema_version"] == 3
    assert "mein_profil" in payload


def test_profile_migration_rewrite_uses_atomic_json_writer(tmp_path, monkeypatch):
    from dragontools.core import profile_manager as module

    path = tmp_path / "h265_profiles.json"
    path.write_text(
        json.dumps(
            {
                "_schema_version": 0,
                "legacy": {
                    "label": "Legacy",
                    "crf": 22,
                    "encoder_options": {"encoder": "cpu"},
                },
            }
        ),
        encoding="utf-8",
    )

    captured: list[tuple[Path, dict]] = []
    monkeypatch.setattr(
        module,
        "write_json_atomic",
        lambda target, data: captured.append((Path(target), dict(data))),
    )

    manager = module.ProfileManager(path)

    assert "legacy" in manager.data
    assert captured, "Eine migrierte Profildatei muss atomar zurückgeschrieben werden."
    assert captured[0][0] == path
    assert captured[0][1]["_schema_version"] == 3


def test_profile_manager_failed_set_does_not_publish_unsaved_profile(tmp_path, monkeypatch):
    import pytest

    from dragontools.core import profile_manager as module

    path = tmp_path / "h265_profiles.json"
    manager = module.ProfileManager(path)

    def fail_write(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(module, "write_json_atomic", fail_write)
    with pytest.raises(OSError, match="disk full"):
        manager.set(
            "unsaved",
            {"label": "Unsaved", "codec": "h265", "encoder_options": {"encoder": "cpu"}},
        )

    assert "unsaved" not in manager._user
    assert "unsaved" not in manager.data


def test_profile_manager_failed_delete_keeps_profile_in_memory(tmp_path, monkeypatch):
    import pytest

    from dragontools.core import profile_manager as module

    path = tmp_path / "h265_profiles.json"
    manager = module.ProfileManager(path)
    assert manager.set(
        "keep_me",
        {"label": "Keep", "codec": "h265", "encoder_options": {"encoder": "cpu"}},
    )
    before = manager.get("keep_me")

    def fail_write(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(module, "write_json_atomic", fail_write)
    with pytest.raises(OSError, match="disk full"):
        manager.delete("keep_me")

    assert manager.get("keep_me") == before
    assert "keep_me" in manager._user


def test_profile_manager_migration_write_failure_does_not_break_profile_loading(tmp_path, monkeypatch):
    import json

    from dragontools.core import profile_manager as module

    path = tmp_path / "h265_profiles.json"
    path.write_text(json.dumps({
        "_schema_version": 0,
        "legacy": {"label": "Legacy", "crf": 22, "encoder_options": {"encoder": "cpu"}},
    }), encoding="utf-8")
    reports: list[tuple] = []

    monkeypatch.setattr(
        module,
        "write_json_atomic",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("read only")),
    )

    manager = module.ProfileManager(path, reporter=lambda *args: reports.append(args))

    assert manager.get("legacy")["codec"] == "h265"
    assert any("nur für diese Sitzung" in str(args[0]) for args in reports)
    assert json.loads(path.read_text(encoding="utf-8"))["_schema_version"] == 0
