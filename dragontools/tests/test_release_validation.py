from __future__ import annotations

import json


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_current_refactor_modules_are_release_smoke_checked():
    from dragontools.core.release_validation_package import _SMOKE_MODULES

    checked = {path.as_posix() for path in _SMOKE_MODULES}
    expected = {
        "worker/tool_process_lifecycle.py",
        "worker/move_batch_executor.py",
        "rules/pipeline_capabilities.py",
        "rules/pipeline_policy.py",
        "rules/audio_plan_policy.py",
        "core/online_metadata_tmdb_resolver.py",
        "core/online_metadata_tmdb_suggestions.py",
        "core/online_metadata_tmdb_transport.py",
        "core/online_metadata_tvdb_candidates.py",
        "worker/subtitle_sidecar_plan.py",
        "worker/subtitle_sidecar_targets.py",
        "core/move_conflict_transactions.py",
        "core/move_journal_adapter.py",
        "core/move_transfer_executor.py",
        "core/media_library_path_mappings.py",
        "core/media_library_series_paths.py",
        "worker/converter_media_probe.py",
        "worker/converter_process_executor.py",
        "worker/converter_progress_parser.py",
        "core/file_override_normalization.py",
        "core/media_analyzer_metadata.py",
        "core/media_analyzer_result.py",
        "core/update_check.py",
        "gui/update_checker.py",
        "worker/media_contract_builder.py",
        "worker/media_contract_types.py",
        "worker/output_probe.py",
        "worker/output_contract_verifier.py",
    }
    assert expected <= checked


def _write_package_smoke_files(root):
    from dragontools.core.release_validation_package import _SMOKE_MODULES

    package = root / "dragontools"
    for name in ("core", "gui", "worker", "rules", "subtitle", "config"):
        (package / name).mkdir(parents=True, exist_ok=True)
    legacy_fixture_modules = (
        "core/settings.py",
        "core/version.py",
        "core/paths.py",
        "core/path_syntax.py",
        "core/path_defaults.py",
        "core/formatting.py",
        "core/tool_diagnostics.py",
        "core/batch_preflight.py",
        "core/batch_preflight_storage.py",
        "core/jellyfin_nfo.py",
        "core/media_library.py",
        "core/media_library_db.py",
        "core/media_library_export.py",
        "core/media_library_jellyfin.py",
        "core/media_library_paths.py",
        "core/media_library_repository.py",
        "core/media_library_scan.py",
        "core/media_library_search.py",
        "core/media_library_types.py",
        "core/media_library_utils.py",
        "core/move_conflicts.py",
        "core/movie_renamer.py",
        "core/movie_renamer_models.py",
        "core/movie_renamer_parsing.py",
        "core/movie_renamer_candidates.py",
        "core/online_metadata.py",
        "core/online_metadata_common.py",
        "core/online_metadata_types.py",
        "core/online_metadata_config.py",
        "core/online_metadata_parsing.py",
        "core/online_metadata_cache_paths.py",
        "core/online_metadata_payload.py",
        "core/online_metadata_service.py",
        "core/online_metadata_tmdb.py",
        "core/online_metadata_tvdb.py",
        "core/online_metadata_tvdb_helpers.py",
        "core/quality_tester.py",
        "core/audio_video_matcher.py",
        "core/audio_video_match_utils.py",
        "core/audio_video_frame_analysis.py",
        "core/audio_video_time_mapping.py",
        "core/audio_video_match_services.py",
        "core/audio_video_match_models.py",
        "core/audio_sync_planner.py",
        "core/replacement_reminders.py",
        "core/changelog.py",
        "core/project_info.py",
        "core/release_validation.py",
        "core/release_validation_common.py",
        "core/release_validation_environment.py",
        "core/release_validation_package.py",
        "core/release_packaging.py",
        "gui/main_window.py",
        "gui/main_window_tabs.py",
        "gui/main_window_recovery.py",
        "gui/main_window_actions.py",
        "gui/main_window_backup_actions.py",
        "gui/main_window_convert_actions.py",
        "gui/main_window_help_actions.py",
        "gui/main_window_metadata_actions.py",
        "gui/main_window_profile_actions.py",
        "gui/main_window_settings_actions.py",
        "gui/main_window_system_actions.py",
        "gui/settings_dialog.py",
        "gui/encoder_settings_controller.py",
        "gui/encoder_settings_options.py",
        "gui/encoder_settings_panels.py",
        "gui/encoder_settings_persistence.py",
        "gui/encoder_settings_profiles.py",
        "gui/convert_widget.py",
        "gui/convert_widget_composition.py",
        "gui/convert_widget_paths.py",
        "gui/convert_widget_runtime_ui.py",
        "gui/convert_widget_recovery.py",
        "gui/convert_widget_host_actions.py",
        "gui/convert_widget_queue_actions.py",
        "gui/convert_widget_queue_dragdrop.py",
        "gui/convert_widget_queue_management.py",
        "gui/convert_widget_queue_window_actions.py",
        "gui/convert_widget_queue_context_actions.py",
        "gui/convert_widget_queue_override_actions.py",
        "gui/convert_widget_encoder_override.py",
        "gui/convert_widget_queue_badges.py",
        "gui/convert_widget_source_visual_actions.py",
        "gui/settings_sections/__init__.py",
        "gui/settings_sections/base.py",
        "gui/settings_sections/storage.py",
        "gui/settings_sections/runtime.py",
        "gui/settings_sections/media.py",
        "gui/settings_sections/video.py",
        "gui/settings_sections/safety.py",
        "gui/conversion_controller.py",
        "gui/conversion_start_coordinator.py",
        "gui/conversion_worker_factory.py",
        "gui/conversion_worker_lifecycle.py",
        "gui/conversion_progress_presenter.py",
        "gui/conversion_diagnostics.py",
        "gui/media_library_dialog.py",
        "gui/media_library_dialog_view.py",
        "gui/media_library_dialog_service.py",
        "gui/media_library_dialog_presenter.py",
        "gui/media_library_maintenance_controller.py",
        "gui/media_library_mapping_controller.py",
        "gui/media_library_search_controller.py",
        "gui/media_library_scan_controller.py",
        "gui/preflight_dialog.py",
        "gui/preflight_widgets.py",
        "gui/preflight_widget_common.py",
        "gui/preflight_series_widget.py",
        "gui/preflight_film_widget.py",
        "gui/preflight_view.py",
        "gui/preflight_metadata.py",
        "gui/move_preflight_controller.py",
        "gui/move_preflight_workflow.py",
        "gui/move_lifecycle_coordinator.py",
        "gui/move_request_dialogs.py",
        "gui/replacement_reminder_dialog.py",
        "gui/movie_renamer_widget.py",
        "gui/movie_renamer_view.py",
        "gui/movie_renamer_table_controller.py",
        "gui/movie_renamer_resolver.py",
        "gui/movie_renamer_actions.py",
        "gui/quality_tester_widget.py",
        "gui/quality_file_compare_dialog.py",
        "gui/audio_video_matcher_widget.py",
        "gui/media_info_dialog.py",
        "gui/media_info_text_builder.py",
        "gui/changelog_dialog.py",
        "gui/video_file_input.py",
        "gui/file_drop_widgets.py",
        "gui/journal_resume_base.py",
        "gui/subtitle_widget.py",
        "gui/subtitle_widget_workers.py",
        "gui/subtitle_widget_files.py",
        "worker/converter_thread.py",
        "worker/converter_runtime_builder.py",
        "worker/converter_run_loop.py",
        "worker/converter_lifecycle.py",
        "worker/converter_file_executor.py",
        "worker/converter_control.py",
        "worker/dv_processing_pipeline.py",
        "worker/dv_pipeline_context.py",
        "worker/dv_encode_command.py",
        "worker/dv_command_runner.py",
        "worker/dv_pipeline_stages.py",
        "worker/worker_contracts.py",
        "core/json_io.py",
        "core/online_metadata_cache.py",
        "subtitle/tool_logging.py",
        "worker/quality_test_thread.py",
        "worker/quality_compare_thread.py",
        "worker/audio_video_match_thread.py",
        "worker/postprocess_service.py",
        "worker/trickplay_service.py",
        "rules/audio_rules.py",
        "rules/move_rules.py",
        "rules/move_rule_config.py",
        "rules/move_series_detection.py",
        "rules/move_path_helpers.py",
        "rules/move_series_directories.py",
        "rules/audio_rule_basics.py",
        "rules/audio_rule_migration.py",
        "rules/audio_rule_repository.py",
        "rules/audio_transcode_policy.py",
        "rules/audio_selection.py",
        "rules/subtitle_rule_config.py",
        "rules/subtitle_rules.py",
        "rules/subtitle_plan_models.py",
        "rules/subtitle_selection.py",
        "rules/subtitle_keep_policy.py",
        "rules/subtitle_burn_policy.py",
        "rules/subtitle_storage.py",
        "core/batch_preflight_formatting.py",
        "core/batch_preflight_decisions.py",
        "core/batch_preflight_rows.py",
        "core/batch_preflight_report.py",
        "core/media_library_classification.py",
        "core/media_library_scope.py",
        "core/media_library_query.py",
        "core/media_library_search_service.py",
        "core/logger_paths.py",
        "core/logger_verbose.py",
        "core/logger_messages.py",
        "core/media_analyzer.py",
        "core/media_analyzer_io.py",
        "core/media_analyzer_streams.py",
        "core/move_journal.py",
        "core/move_journal_contracts.py",
        "core/move_journal_storage.py",
        "core/move_journal_resume.py",
        "core/move_journal_utils.py",
        "core/online_metadata_tvdb_resolver.py",
        "core/online_metadata_tvdb_suggestions.py",
        "core/online_metadata_tvdb_transport.py",
        "gui/convert_widget_layout.py",
        "gui/convert_widget_layout_components.py",
        "gui/convert_widget_layout_options.py",
        "gui/convert_widget_layout_runtime.py",
        "gui/convert_widget_file_queue.py",
        "gui/convert_widget_queue_add.py",
        "gui/convert_widget_queue_remove.py",
        "gui/convert_widget_override_dialog.py",
        "gui/convert_override_lifecycle.py",
        "gui/convert_override_state.py",
        "gui/convert_override_tracks.py",
        "gui/convert_override_groups.py",
        "gui/quality_tester_run_dialog.py",
        "gui/quality_tester_run_config.py",
        "gui/quality_tester_files.py",
        "gui/quality_tester_execution.py",
        "gui/rules_audio_tab.py",
        "gui/rules_audio_tab_sections.py",
        "gui/rules_audio_tab_channels.py",
        "gui/rules_audio_tab_state.py",
    )
    all_modules = {str(rel).replace("\\", "/") for rel in _SMOKE_MODULES}
    all_modules.update(legacy_fixture_modules)
    for rel in sorted(all_modules):
        (package / rel).parent.mkdir(parents=True, exist_ok=True)
        path = package / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# smoke\nVALUE = 1\n", encoding="utf-8")


def test_release_validation_checks_required_files_and_schema(tmp_path):
    from dragontools.core.release_validation import validate_release

    root = tmp_path
    (root / "DragonToolsV9.py").write_text("# app", encoding="utf-8")
    (root / "Bilder").mkdir()
    (root / "Bilder" / "splash_pyinstaller.png").write_bytes(b"png")
    (root / "help.html").write_text("<html></html>", encoding="utf-8")
    (root / "Handbuch").mkdir()
    (root / "Handbuch" / "Handbuch.pdf").write_bytes(b"%PDF")
    (root / "Aenderungshistorie").mkdir()
    (root / "Aenderungshistorie" / "CHANGELOG.json").write_text('{"format_version": 1, "sections": [{"title": "Überblick", "blocks": ["V9"]}]}', encoding="utf-8")
    _write_package_smoke_files(root)
    config = root / "dragontools" / "config"
    _write_json(config / "default_audio_rules.json", {"_schema_version": 4})
    _write_json(config / "default_subtitle_rules.json", {"_schema_version": 6})
    _write_json(config / "default_move_rules.json", {"_schema_version": 1})
    _write_json(config / "default_renamer_rules.json", {"_schema_version": 2})
    _write_json(config / "default_profiles.json", {"_schema_version": 3})

    checks = validate_release(root)
    by_title = {check.title: check for check in checks}

    assert by_title["Quell-Startdatei"].status == "ok"
    assert by_title["Schema: Audio-Regeln"].status == "ok"
    assert by_title["PDF-Handbuch"].status == "ok"
    assert by_title["Python-Paket-Smoke-Test"].status == "ok"
    assert by_title["OpenCV-Bildanalyse"].status in {"ok", "warn"}
    assert by_title["PyInstaller-Build"].status == "warn"


def test_release_validation_treats_schema_mismatch_as_error(tmp_path):
    from dragontools.core.release_validation import validate_release

    config = tmp_path / "dragontools" / "config"
    _write_json(config / "default_subtitle_rules.json", {"_schema_version": 3})

    checks = validate_release(tmp_path)
    by_title = {check.title: check for check in checks}

    assert by_title["Schema: Untertitel-Regeln"].status == "error"
    assert "erwartet 6" in by_title["Schema: Untertitel-Regeln"].detail


def test_release_validation_warns_about_private_paths(tmp_path):
    from dragontools.core.release_validation import validate_release

    root = tmp_path
    (root / "help.html").write_text(r"C:\Users\Mar" + "ku\\Documents\\DragonTools", encoding="utf-8")

    checks = validate_release(root)

    assert any(check.status == "warn" and "Datenschutz" in check.title for check in checks)


def test_app_bundle_validation_checks_exe_not_source_files(tmp_path):
    from dragontools.core.release_validation import validate_release
    from dragontools.core.settings import APP_VERSION

    app_dir = tmp_path / f"DragonToolsV{APP_VERSION}"
    data_dir = app_dir / "Daten"
    (app_dir / f"DragonToolsV{APP_VERSION}.exe").parent.mkdir(parents=True)
    (app_dir / f"DragonToolsV{APP_VERSION}.exe").write_bytes(b"exe")
    (data_dir / "help.html").parent.mkdir(parents=True)
    (data_dir / "help.html").write_text("<html>" + "Mar" + "ku" + "</html>", encoding="utf-8")
    (data_dir / "Handbuch").mkdir()
    (data_dir / "Handbuch" / "Handbuch.pdf").write_bytes(b"%PDF")
    (data_dir / "Aenderungshistorie").mkdir()
    (data_dir / "Aenderungshistorie" / "CHANGELOG.json").write_text('{"format_version": 1, "sections": [{"title": "Überblick", "blocks": ["V9"]}]}', encoding="utf-8")
    _write_package_smoke_files(data_dir / "Python")
    config = data_dir / "dragontools" / "config"
    _write_json(config / "default_audio_rules.json", {"_schema_version": 4})
    _write_json(config / "default_subtitle_rules.json", {"_schema_version": 6})
    _write_json(config / "default_move_rules.json", {"_schema_version": 1})
    _write_json(config / "default_renamer_rules.json", {"_schema_version": 2})
    _write_json(config / "default_profiles.json", {"_schema_version": 3})

    checks = validate_release(data_dir, mode="app")
    by_title = {check.title: check for check in checks}
    titles = set(by_title)

    assert by_title["Startdatei"].status == "ok"
    assert by_title["Python-Quellpaket"].status == "ok"
    assert by_title["Runtime-Konfiguration"].status == "ok"
    assert by_title["Python-Paket-Smoke-Test"].status == "ok"
    assert by_title["OpenCV-Bildanalyse"].status in {"ok", "warn"}
    assert "Quell-Startdatei" not in titles
    assert "Versionierte PyInstaller-Spec" not in titles
    assert "Build-Skript" not in titles
    assert "PyInstaller-Build" not in titles
    assert not any(title.startswith("Datenschutz") for title in titles)


def test_format_release_checks_summarizes_errors_and_warnings():
    from dragontools.core.release_validation import ReleaseCheck, format_release_checks

    text = format_release_checks([
        ReleaseCheck("ok", "OK"),
        ReleaseCheck("warn", "Warnung"),
        ReleaseCheck("error", "Fehler"),
    ])

    assert "1 Fehler, 1 Warnungen" in text

def test_source_only_manifest_makes_source_archive_self_consistent(tmp_path):
    from dragontools.core.release_validation import validate_release
    from dragontools.core.settings import APP_VERSION

    root = tmp_path
    (root / "DragonToolsV9.py").write_text("# app", encoding="utf-8")
    (root / "help.html").write_text("<html></html>", encoding="utf-8")
    (root / "DragonToolsV9_Dokumentation.docx").write_bytes(b"docx")
    (root / "Handbuch").mkdir()
    (root / "Handbuch" / "Handbuch.pdf").write_bytes(b"%PDF")
    (root / "Aenderungshistorie").mkdir()
    (root / "Aenderungshistorie" / "CHANGELOG.json").write_text(
        '{"format_version": 1, "sections": [{"title": "Ueberblick", "blocks": ["V9"]}]}',
        encoding="utf-8",
    )
    _write_package_smoke_files(root)
    config = root / "dragontools" / "config"
    _write_json(config / "default_audio_rules.json", {"_schema_version": 4})
    _write_json(config / "default_subtitle_rules.json", {"_schema_version": 6})
    _write_json(config / "default_move_rules.json", {"_schema_version": 1})
    _write_json(config / "default_renamer_rules.json", {"_schema_version": 2})
    _write_json(config / "default_profiles.json", {"_schema_version": 3})
    (root / "requirements-runtime.txt").write_text(
        "PyQt6>=6.4,<7\ncryptography>=42,<51\n", encoding="utf-8"
    )
    (root / "requirements-test.txt").write_text(
        "-r requirements-runtime.txt\npytest>=8\npytest-qt>=4.4\n", encoding="utf-8"
    )
    (root / "pytest.ini").write_text(
        "[pytest]\nqt_api = pyqt6\nmarkers =\n    media_integration: real media tests\n    dv_hdr_integration: real DV/HDR tests\n",
        encoding="utf-8",
    )
    (root / "release_manifest.json").write_text(
        json.dumps({
            "schema_version": 1,
            "profile": "source-only",
            "app_version": APP_VERSION,
            "build_inputs_included": False,
            "manual_pdf_included": True,
            "test_environment_included": True,
        }),
        encoding="utf-8",
    )

    checks = validate_release(root, mode="source")
    by_title = {check.title: check for check in checks}

    assert by_title["Release-Manifest"].status == "ok"
    assert by_title["Build-Quelldateien"].status == "ok"
    assert by_title["PDF-Handbuch"].status == "ok"
    assert by_title["Testumgebung"].status == "ok"
    assert by_title["PyInstaller-Build"].status == "ok"
    assert "Versionierte PyInstaller-Spec" not in by_title
    assert "Build-Skript" not in by_title



def test_release_validation_rejects_python_bytecode_artifacts(tmp_path):
    from dragontools.core.release_validation import validate_release

    cache_dir = tmp_path / "dragontools" / "core" / "__pycache__"
    cache_dir.mkdir(parents=True)
    (cache_dir / "legacy.cpython-312.pyc").write_bytes(b"bytecode")
    (tmp_path / "orphan.pyo").write_bytes(b"optimized")

    checks = validate_release(tmp_path)
    by_title = {check.title: check for check in checks}

    assert by_title["Release-Bytecode"].status == "error"
    assert "__pycache__" in by_title["Release-Bytecode"].detail
    assert ".pyo" in by_title["Release-Bytecode"].detail


def test_release_validation_accepts_clean_tree_without_bytecode(tmp_path):
    from dragontools.core.release_validation import validate_release

    (tmp_path / "dragontools").mkdir()
    (tmp_path / "dragontools" / "module.py").write_text("VALUE = 1\n", encoding="utf-8")

    checks = validate_release(tmp_path)
    by_title = {check.title: check for check in checks}

    assert by_title["Release-Bytecode"].status == "ok"


def test_package_only_manifest_validates_code_only_release(tmp_path):
    from dragontools.core.release_validation import validate_release
    from dragontools.core.settings import APP_VERSION

    root = tmp_path
    _write_package_smoke_files(root)
    config = root / "dragontools" / "config"
    _write_json(config / "default_audio_rules.json", {"_schema_version": 4})
    _write_json(config / "default_subtitle_rules.json", {"_schema_version": 6})
    _write_json(config / "default_move_rules.json", {"_schema_version": 1})
    _write_json(config / "default_renamer_rules.json", {"_schema_version": 2})
    _write_json(config / "default_profiles.json", {"_schema_version": 3})
    (root / "requirements-runtime.txt").write_text(
        "PyQt6>=6.4,<7\ncryptography>=42,<51\n", encoding="utf-8"
    )
    (root / "requirements-test.txt").write_text(
        "-r requirements-runtime.txt\npytest>=8\npytest-qt>=4.4\n", encoding="utf-8"
    )
    (root / "pytest.ini").write_text(
        "[pytest]\nqt_api = pyqt6\nmarkers =\n    media_integration: real media tests\n    dv_hdr_integration: real DV/HDR tests\n",
        encoding="utf-8",
    )
    (root / "release_manifest.json").write_text(
        json.dumps({
            "schema_version": 1,
            "profile": "package-only",
            "app_version": APP_VERSION,
            "build_inputs_included": False,
            "manual_pdf_included": False,
            "test_environment_included": True,
        }),
        encoding="utf-8",
    )

    checks = validate_release(root, mode="source")
    by_title = {check.title: check for check in checks}

    assert by_title["Release-Manifest"].status == "ok"
    assert by_title["Quellpaket-Profil"].status == "ok"
    assert by_title["Anwendungsartefakte"].status == "ok"
    assert by_title["Testumgebung"].status == "ok"
    assert by_title["PyInstaller-Build"].status == "ok"
    assert by_title["Python-Paket-Smoke-Test"].status == "ok"
    assert not any(check.status == "error" for check in checks)


def test_release_validation_rejects_test_cache_directories(tmp_path):
    from dragontools.core.release_validation import validate_release

    cache = tmp_path / ".pytest_cache"
    cache.mkdir()
    (cache / "README.md").write_text("cache", encoding="utf-8")

    checks = validate_release(tmp_path)
    by_title = {check.title: check for check in checks}

    assert by_title["Release-Bytecode"].status == "error"
    assert ".pytest_cache" in by_title["Release-Bytecode"].detail


def test_release_validation_detects_stale_built_documentation(tmp_path):
    from dragontools.core.release_validation import validate_release
    from dragontools.core.settings import APP_VERSION

    root = tmp_path
    (root / "DragonToolsV9.py").write_text("# app", encoding="utf-8")
    (root / "help.html").write_text("<html>aktuell</html>", encoding="utf-8")
    (root / "Handbuch").mkdir()
    (root / "Handbuch" / "Handbuch.pdf").write_bytes(b"%PDF-current")
    (root / "Aenderungshistorie").mkdir()
    (root / "Aenderungshistorie" / "CHANGELOG.json").write_text(
        '{"format_version": 1, "sections": [{"title": "Aktuell", "blocks": ["V9.8.2"]}]}',
        encoding="utf-8",
    )
    (root / "Aenderungshistorie" / "CHANGELOG.txt").write_text("aktuell\n", encoding="utf-8")
    _write_package_smoke_files(root)
    config = root / "dragontools" / "config"
    _write_json(config / "default_audio_rules.json", {"_schema_version": 4})
    _write_json(config / "default_subtitle_rules.json", {"_schema_version": 6})
    _write_json(config / "default_move_rules.json", {"_schema_version": 1})
    _write_json(config / "default_renamer_rules.json", {"_schema_version": 2})
    _write_json(config / "default_profiles.json", {"_schema_version": 3})

    dist = root / "dist" / f"DragonToolsV{APP_VERSION}"
    data = dist / "Daten"
    (dist / f"DragonToolsV{APP_VERSION}.exe").parent.mkdir(parents=True)
    (dist / f"DragonToolsV{APP_VERSION}.exe").write_bytes(b"exe")
    (data / "help.html").parent.mkdir(parents=True)
    (data / "help.html").write_text("<html>ALT</html>", encoding="utf-8")
    (data / "Handbuch").mkdir()
    (data / "Handbuch" / "Handbuch.pdf").write_bytes(b"%PDF-current")
    (data / "Aenderungshistorie").mkdir()
    (data / "Aenderungshistorie" / "CHANGELOG.json").write_text(
        (root / "Aenderungshistorie" / "CHANGELOG.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (data / "Aenderungshistorie" / "CHANGELOG.txt").write_text("aktuell\n", encoding="utf-8")
    _write_package_smoke_files(data / "Python")
    (data / "dragontools" / "config").mkdir(parents=True, exist_ok=True)
    for name in (
        "default_audio_rules.json",
        "default_subtitle_rules.json",
        "default_move_rules.json",
        "default_renamer_rules.json",
        "default_profiles.json",
    ):
        (data / "dragontools" / "config" / name).write_bytes((config / name).read_bytes())

    checks = validate_release(root, mode="source")
    by_title = {check.title: check for check in checks}

    assert by_title["Build: Help-Aktualität"].status == "error"
    assert "veraltet" in by_title["Build: Help-Aktualität"].detail
    assert by_title["Build: Handbuch-Aktualität"].status == "ok"
    assert by_title["Build: Changelog-JSON-Aktualität"].status == "ok"
    assert by_title["Build: Changelog-TXT-Aktualität"].status == "ok"
