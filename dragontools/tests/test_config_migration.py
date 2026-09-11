from __future__ import annotations

import json


def test_profile_manager_migrates_legacy_profile_file(tmp_path, monkeypatch):
    import dragontools.core.config_migration as migration
    from dragontools.core.profile_manager import ProfileManager

    monkeypatch.setattr(migration, "MIGRATION_LOG_PATH", tmp_path / "migration.log")
    profile_path = tmp_path / "h265_profiles.json"
    profile_path.write_text(
        json.dumps(
            {
                "mein_profil": {
                    "codec": "h265",
                    "crf": 23,
                    "preset": "medium",
                }
            }
        ),
        encoding="utf-8",
    )

    manager = ProfileManager(profile_path)
    profile = manager.get("mein_profil")
    saved = json.loads(profile_path.read_text(encoding="utf-8"))

    assert saved["_schema_version"] == 3
    assert profile["scale"] == "original"
    assert profile["encoder_options"]["encoder"] == "cpu"
    assert profile["encoder_options"]["bf"] == 8
    assert "Schema 0 -> 3" in (tmp_path / "migration.log").read_text(encoding="utf-8")


def test_profile_migration_removes_legacy_qsv_lookahead_flag():
    from dragontools.core.config_migration import migrate_encoder_profile

    migrated, messages = migrate_encoder_profile(
        "qsv_alt",
        {
            "codec": "h265",
            "crf": 23,
            "preset": "medium",
            "scale": "original",
            "encoder_options": {
                "encoder": "qsv",
                "preset": "medium",
                "q": 23,
                "lookahead": False,
                "lookahead_depth": 40,
            },
        },
    )

    assert "lookahead" not in migrated["encoder_options"]
    assert migrated["encoder_options"]["lookahead_depth"] == 40
    assert any("veraltete QSV-Option" in message for message in messages)


def test_profile_migration_clamps_qsv_lookahead_depth():
    from dragontools.core.config_migration import migrate_encoder_profile

    migrated_high, _messages = migrate_encoder_profile(
        "qsv_high",
        {
            "codec": "h265",
            "crf": 23,
            "preset": "medium",
            "scale": "original",
            "encoder_options": {
                "encoder": "qsv",
                "q": 23,
                "lookahead_depth": 250,
            },
        },
    )
    migrated_low, _messages = migrate_encoder_profile(
        "qsv_low",
        {
            "codec": "h265",
            "crf": 23,
            "preset": "medium",
            "scale": "original",
            "encoder_options": {
                "encoder": "qsv",
                "q": 23,
                "lookahead_depth": 0,
            },
        },
    )

    assert migrated_high["encoder_options"]["lookahead_depth"] == 100
    assert migrated_low["encoder_options"]["lookahead_depth"] == 1


def test_audio_rules_migration_adds_schema_and_stereo_copy_range(tmp_path, monkeypatch):
    import dragontools.core.config_migration as migration
    from dragontools.rules.audio_rules import migrate_audio_rules

    monkeypatch.setattr(migration, "MIGRATION_LOG_PATH", tmp_path / "migration.log")
    legacy = {
        "language_priority": ["de"],
        "channel_rules": {
            "stereo": {"max_channels": 2, "target_codec": "aac", "max_bitrate_k": 256},
            "surround_51": {"max_channels": 6, "target_codec": "eac3", "max_bitrate_k": 640},
            "surround_71": {"max_channels": 8, "target_codec": "eac3", "max_bitrate_k": 640},
        },
    }

    migrated = migrate_audio_rules(legacy, source_path=tmp_path / "audio_rules.json")

    assert migrated["_schema_version"] == 4
    assert migrated["channel_rules"]["stereo"]["max_bitrate_k"] == 192
    assert migrated["channel_rules"]["stereo"]["copy_min_bitrate_k"] == 192
    assert migrated["channel_rules"]["stereo"]["copy_max_bitrate_k"] == 256
    assert migrated["channel_rules"]["surround_51"]["copy_min_bitrate_k"] == 428
    assert migrated["channel_rules"]["surround_51"]["copy_max_bitrate_k"] == 640
    assert migrated["channel_rules"]["surround_71"]["copy_min_bitrate_k"] == 768
    assert migrated["channel_rules"]["surround_71"]["copy_max_bitrate_k"] == 1536
    assert migrated["audio_processing"]["drc_enabled"] is False
    assert migrated["audio_processing"]["drc_scale"] == 1.0
    assert migrated["audio_processing"]["loudnorm_enabled"] is False
    log_text = (tmp_path / "migration.log").read_text(encoding="utf-8")
    assert "Stereo-Kopierbereich" in log_text
    assert "5.1-Kopierbereich" in log_text
    assert "7.1-Kopierbereich" in log_text
    assert "Audio-Dynamik" in log_text


def test_move_rules_migration_adds_missing_defaults():
    from dragontools.rules.move_rules import migrate_move_rules

    migrated = migrate_move_rules({"series_patterns": []})

    assert migrated["_schema_version"] == 1
    assert migrated["series_patterns"] == []
    assert migrated["series_test_examples"]
    assert migrated["folder_structure"]["series"]
    assert migrated["folder_structure"]["movie"]
    assert migrated["folder_structure"]["anime"]


def test_profile_migration_uses_crf22_only_for_h265_cpu_fallback():
    from dragontools.core.config_migration import migrate_encoder_profile

    cpu, _ = migrate_encoder_profile(
        "legacy_cpu",
        {"codec": "h265", "encoder_options": {"encoder": "cpu"}},
    )
    nvenc, _ = migrate_encoder_profile(
        "legacy_nvenc",
        {"codec": "h265", "encoder_options": {"encoder": "nvenc"}},
    )

    assert cpu["crf"] == 22
    assert nvenc["crf"] == 23


def test_config_migration_atomic_writer_delegates_to_shared_crash_safe_writer(tmp_path, monkeypatch):
    import dragontools.core.config_migration as migration

    calls = []

    def fake_atomic(path, data):
        calls.append((path, data))

    monkeypatch.setattr(migration, "atomic_write_json", fake_atomic)
    target = tmp_path / "rules.json"
    payload = {"_schema_version": 4, "value": 1}

    migration.write_json_atomic(target, payload)

    assert calls == [(target, payload)]


def test_profile_migration_normalizes_invalid_backend_and_legacy_types():
    from dragontools.core.config_migration import migrate_encoder_profile

    invalid, messages = migrate_encoder_profile(
        "legacy_invalid",
        {
            "codec": "h265",
            "crf": "22.0",
            "encoder_options": {
                "encoder": "cuda",
                "bf": "8.0",
                "rc_lookahead": "40.0",
            },
        },
    )
    nvenc, _ = migrate_encoder_profile(
        "legacy_nvenc_strings",
        {
            "codec": "h265",
            "crf": "19.0",
            "encoder_options": {
                "encoder": "nvenc",
                "cq": "19.0",
                "bf": "4.0",
                "rc_lookahead": "32.0",
                "aq_strength": "8.0",
                "spatial_aq": "false",
                "temporal_aq": "0",
            },
        },
    )

    assert invalid["encoder_options"]["encoder"] == "cpu"
    assert invalid["encoder_options"]["bf"] == 8
    assert invalid["encoder_options"]["rc_lookahead"] == 40
    assert any("unbekannten Encoder" in message for message in messages)
    assert nvenc["crf"] == 19
    assert nvenc["encoder_options"]["cq"] == 19
    assert nvenc["encoder_options"]["bf"] == 4
    assert nvenc["encoder_options"]["rc_lookahead"] == 32
    assert nvenc["encoder_options"]["aq_strength"] == 8
    assert nvenc["encoder_options"]["spatial_aq"] is False
    assert nvenc["encoder_options"]["temporal_aq"] is False


def test_rule_migrations_normalize_string_booleans():
    from dragontools.rules.audio_rules import migrate_audio_rules
    from dragontools.rules.renamer_rules import migrate_renamer_rules
    from dragontools.rules.subtitle_rules import migrate_subtitle_rules

    audio = migrate_audio_rules({
        "ignore_commentary_tracks": "false",
        "ignore_descriptive_audio": "0",
        "extra_stereo": "false",
        "extra_stereo_bitrate_k": "320.0",
        "audio_processing": {
            "drc_enabled": "false",
            "loudnorm_enabled": "0",
        },
    })
    renamer = migrate_renamer_rules({
        "matching": {
            "fuzzy_fallback": "false",
            "retry_without_year": "0",
            "fuzzy_prefix_min_words": "4.0",
        },
    })
    subtitle = migrate_subtitle_rules({
        "force_priority": "false",
        "dv_extract_external_subs": "0",
        "additional_sidecars_enabled": "1",
        "text_to_srt_sidecar_enabled": "false",
        "burn_in_rules": {
            "auto_burn_forced": "false",
            "ask_if_ambiguous": "0",
            "never_burn_if_no_audio_language": "false",
            "forced_plausibility": {"enabled": "false"},
        },
        "keep_rules": {
            "keep_forced": "false",
            "keep_selected_languages": "0",
            "keep_regular": "false",
        },
    })

    assert audio["ignore_commentary_tracks"] is False
    assert audio["ignore_descriptive_audio"] is False
    assert audio["extra_stereo"] is False
    assert audio["extra_stereo_bitrate_k"] == 320
    assert audio["audio_processing"]["drc_enabled"] is False
    assert audio["audio_processing"]["loudnorm_enabled"] is False
    assert renamer["matching"]["fuzzy_fallback"] is False
    assert renamer["matching"]["retry_without_year"] is False
    assert renamer["matching"]["fuzzy_prefix_min_words"] == 4
    assert subtitle["force_priority"] is False
    assert subtitle["dv_extract_external_subs"] is False
    assert subtitle["additional_sidecars_enabled"] is True
    assert subtitle["text_to_srt_sidecar_enabled"] is False
    assert subtitle["burn_in_rules"]["auto_burn_forced"] is False
    assert subtitle["burn_in_rules"]["ask_if_ambiguous"] is False
    assert subtitle["burn_in_rules"]["forced_plausibility"]["enabled"] is False
    assert subtitle["keep_rules"]["keep_forced"] is False
    assert subtitle["keep_rules"]["keep_selected_languages"] is False
    assert subtitle["keep_rules"]["keep_regular"] is False


def test_current_subtitle_rules_do_not_log_runtime_marker_as_migration(tmp_path, monkeypatch):
    import dragontools.core.config_migration as migration
    from dragontools.rules.subtitle_rule_config import DEFAULT_SUBTITLE_RULES, migrate_subtitle_rules

    monkeypatch.setattr(migration, "MIGRATION_LOG_PATH", tmp_path / "migration.log")

    migrated = migrate_subtitle_rules(
        dict(DEFAULT_SUBTITLE_RULES),
        source_path=tmp_path / "subtitle_rules.json",
    )

    assert migrated["_legacy_language_rules"] is False
    assert not (tmp_path / "migration.log").exists()


def test_subtitle_migration_renames_schema5_ass_srt_option():
    from dragontools.rules.subtitle_rule_config import migrate_subtitle_rules

    migrated = migrate_subtitle_rules({
        "_schema_version": 5,
        "ass_to_srt_sidecar_enabled": "1",
    })

    assert migrated["_schema_version"] == 6
    assert migrated["text_to_srt_sidecar_enabled"] is True
    assert "ass_to_srt_sidecar_enabled" not in migrated


def test_rule_loader_does_not_rewrite_current_subtitle_rules_for_runtime_marker(tmp_path, monkeypatch):
    from dragontools.rules import rule_loader
    from dragontools.rules.subtitle_rule_config import DEFAULT_SUBTITLE_RULES, migrate_subtitle_rules

    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    rules_path = rules_dir / "subtitle_rules.json"
    rules_path.write_text(
        json.dumps(DEFAULT_SUBTITLE_RULES, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    writes: list[tuple[object, object]] = []

    monkeypatch.setattr(rule_loader, "_rules_dir", lambda: rules_dir)
    monkeypatch.setattr(
        rule_loader,
        "write_json_atomic",
        lambda path, data: writes.append((path, data)),
    )

    loaded = rule_loader.load_named_rules(
        "subtitle_rules",
        migrator=migrate_subtitle_rules,
    )

    assert loaded["_legacy_language_rules"] is False
    assert writes == []
