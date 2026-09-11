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
    assert payload["_schema_version"] == 6


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
