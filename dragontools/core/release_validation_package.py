from __future__ import annotations
import ast
import re
from pathlib import Path
from typing import Iterable

from .release_packaging import find_forbidden_release_artifacts
from .release_validation_common import APP_VERSION, ReleaseCheck, _load_json
from .release_validation_smoke_modules import REFACTOR_SMOKE_MODULES

def _load_release_manifest(root: Path) -> tuple[dict, ReleaseCheck]:
    path = root / "release_manifest.json"
    if not path.is_file():
        return {}, ReleaseCheck(
            "warn",
            "Release-Manifest",
            "Kein release_manifest.json vorhanden; Build-Dateien werden nach Legacy-Regeln geprueft.",
        )
    data = _load_json(path)
    if int(data.get("schema_version", 0) or 0) != 1:
        return data, ReleaseCheck(
            "error",
            "Release-Manifest",
            f"Unbekannte Schema-Version in {path.name}: {data.get('schema_version')!r}",
        )
    profile = str(data.get("profile") or "").strip().casefold()
    if profile not in {"package-only", "source-only", "source-with-build"}:
        return data, ReleaseCheck(
            "error",
            "Release-Manifest",
            f"Unbekanntes Release-Profil: {profile!r}",
        )
    declared_version = str(data.get("app_version") or "").strip()
    if declared_version and declared_version != APP_VERSION:
        return data, ReleaseCheck(
            "error",
            "Release-Manifest",
            f"Manifest-Version {declared_version} passt nicht zu APP_VERSION {APP_VERSION}.",
        )
    return data, ReleaseCheck(
        "ok",
        "Release-Manifest",
        f"Schema 1, Profil {profile}, App-Version {declared_version or APP_VERSION}.",
    )

_PACKAGE_DIRS = ("core", "gui", "worker", "rules", "subtitle", "config")
_SMOKE_MODULES = (
    *REFACTOR_SMOKE_MODULES,
    Path("core") / "settings.py",
    Path("core") / "version.py",
    Path("core") / "paths.py",
    Path("core") / "path_syntax.py",
    Path("core") / "path_defaults.py",
    Path("core") / "formatting.py",
    Path("core") / "tool_diagnostics.py",
    Path("core") / "batch_preflight.py",
    Path("core") / "batch_preflight_formatting.py",
    Path("core") / "batch_preflight_decisions.py",
    Path("core") / "batch_preflight_rows.py",
    Path("core") / "batch_preflight_report.py",
    Path("core") / "batch_preflight_storage.py",
    Path("core") / "jellyfin_nfo.py",
    Path("core") / "media_library.py",
    Path("core") / "media_library_db.py",
    Path("core") / "media_library_export.py",
    Path("core") / "media_library_jellyfin.py", Path("core") / "media_library_movie_paths.py",
    Path("core") / "media_library_paths.py",
    Path("core") / "media_library_repository.py",
    Path("core") / "media_library_scan.py",
    Path("core") / "media_library_search.py",
    Path("core") / "media_library_classification.py",
    Path("core") / "media_library_scope.py",
    Path("core") / "media_library_query.py",
    Path("core") / "media_library_search_service.py",
    Path("core") / "media_library_types.py",
    Path("core") / "media_library_utils.py",
    Path("core") / "logger_paths.py",
    Path("core") / "logger_verbose.py",
    Path("core") / "logger_messages.py",
    Path("core") / "media_analyzer.py",
    Path("core") / "media_analyzer_io.py",
    Path("core") / "media_analyzer_streams.py",
    Path("core") / "move_journal.py",
    Path("core") / "move_journal_contracts.py",
    Path("core") / "move_journal_storage.py",
    Path("core") / "move_journal_resume.py",
    Path("core") / "move_journal_utils.py",
    Path("core") / "move_conflicts.py",
    Path("core") / "movie_renamer.py",
    Path("core") / "movie_renamer_models.py", Path("core") / "movie_renamer_parsing.py",
    Path("core") / "movie_renamer_candidates.py", Path("core") / "movie_renamer_episode_refresh.py",
    Path("core") / "movie_renamer_matching.py",
    Path("core") / "online_metadata.py",
    Path("core") / "online_metadata_common.py",
    Path("core") / "online_metadata_types.py",
    Path("core") / "online_metadata_config.py",
    Path("core") / "online_metadata_parsing.py",
    Path("core") / "online_metadata_cache_paths.py",
    Path("core") / "online_metadata_payload.py",
    Path("core") / "online_metadata_service.py",
    Path("core") / "online_metadata_tmdb.py",
    Path("core") / "online_metadata_tvdb.py",
    Path("core") / "online_metadata_tvdb_helpers.py",
    Path("core") / "online_metadata_tvdb_resolver.py",
    Path("core") / "online_metadata_tvdb_suggestions.py",
    Path("core") / "online_metadata_tvdb_transport.py",
    Path("core") / "quality_tester.py",
    Path("core") / "audio_video_matcher.py",
    Path("core") / "audio_video_match_utils.py",
    Path("core") / "audio_video_frame_analysis.py",
    Path("core") / "audio_video_time_mapping.py",
    Path("core") / "audio_video_match_services.py",
    Path("core") / "audio_video_match_models.py",
    Path("core") / "audio_sync_planner.py",
    Path("core") / "replacement_reminders.py",
    Path("core") / "changelog.py",
    Path("core") / "project_info.py",
    Path("core") / "release_validation.py",
    Path("core") / "release_validation_common.py",
    Path("core") / "release_validation_environment.py",
    Path("core") / "release_validation_package.py",
    Path("core") / "release_packaging.py",
    Path("gui") / "main_window.py",
    Path("gui") / "main_window_tabs.py",
    Path("gui") / "main_window_recovery.py",
    Path("gui") / "main_window_actions.py",
    Path("gui") / "main_window_backup_actions.py",
    Path("gui") / "main_window_convert_actions.py",
    Path("gui") / "main_window_help_actions.py",
    Path("gui") / "main_window_metadata_actions.py",
    Path("gui") / "main_window_profile_actions.py",
    Path("gui") / "main_window_settings_actions.py",
    Path("gui") / "main_window_system_actions.py",
    Path("gui") / "settings_dialog.py",
    Path("gui") / "encoder_settings_controller.py",
    Path("gui") / "encoder_settings_options.py",
    Path("gui") / "encoder_settings_panels.py",
    Path("gui") / "encoder_settings_persistence.py",
    Path("gui") / "encoder_settings_profiles.py",
    Path("gui") / "convert_widget.py",
    Path("gui") / "convert_widget_composition.py",
    Path("gui") / "convert_widget_paths.py",
    Path("gui") / "convert_widget_runtime_ui.py",
    Path("gui") / "convert_widget_recovery.py",
    Path("gui") / "convert_widget_host_actions.py",
    Path("gui") / "convert_widget_queue_actions.py",
    Path("gui") / "convert_widget_queue_dragdrop.py",
    Path("gui") / "convert_widget_queue_management.py",
    Path("gui") / "convert_widget_queue_window_actions.py",
    Path("gui") / "convert_widget_queue_context_actions.py",
    Path("gui") / "convert_widget_queue_override_actions.py",
    Path("gui") / "convert_widget_encoder_override.py",
    Path("gui") / "convert_widget_queue_badges.py",
    Path("gui") / "convert_widget_source_visual_actions.py",
    Path("gui") / "convert_widget_layout.py",
    Path("gui") / "convert_widget_layout_components.py",
    Path("gui") / "convert_widget_layout_options.py",
    Path("gui") / "convert_widget_layout_runtime.py",
    Path("gui") / "convert_widget_file_queue.py",
    Path("gui") / "convert_widget_queue_add.py",
    Path("gui") / "convert_widget_queue_remove.py",
    Path("gui") / "convert_widget_override_dialog.py",
    Path("gui") / "convert_override_lifecycle.py",
    Path("gui") / "convert_override_state.py",
    Path("gui") / "convert_override_tracks.py",
    Path("gui") / "convert_override_groups.py",
    Path("gui") / "settings_sections" / "__init__.py",
    Path("gui") / "settings_sections" / "base.py",
    Path("gui") / "settings_sections" / "storage.py",
    Path("gui") / "settings_sections" / "runtime.py",
    Path("gui") / "settings_sections" / "media.py",
    Path("gui") / "settings_sections" / "video.py",
    Path("gui") / "settings_sections" / "safety.py",
    Path("gui") / "conversion_controller.py",
    Path("gui") / "conversion_start_coordinator.py",
    Path("gui") / "conversion_worker_factory.py",
    Path("gui") / "conversion_worker_lifecycle.py",
    Path("gui") / "conversion_progress_presenter.py",
    Path("gui") / "conversion_diagnostics.py",
    Path("gui") / "media_library_dialog.py",
    Path("gui") / "media_library_dialog_view.py",
    Path("gui") / "media_library_dialog_service.py",
    Path("gui") / "media_library_dialog_presenter.py",
    Path("gui") / "media_library_maintenance_controller.py",
    Path("gui") / "media_library_mapping_controller.py",
    Path("gui") / "media_library_search_controller.py",
    Path("gui") / "media_library_scan_controller.py",
    Path("gui") / "preflight_dialog.py",
    Path("gui") / "preflight_widgets.py",
    Path("gui") / "preflight_widget_common.py",
    Path("gui") / "preflight_series_widget.py",
    Path("gui") / "preflight_film_widget.py", Path("gui") / "preflight_film_hints.py",
    Path("gui") / "preflight_view.py",
    Path("gui") / "preflight_metadata.py",
    Path("gui") / "move_preflight_controller.py",
    Path("gui") / "move_preflight_workflow.py",
    Path("gui") / "move_lifecycle_coordinator.py",
    Path("gui") / "move_request_dialogs.py",
    Path("gui") / "replacement_reminder_dialog.py",
    Path("gui") / "movie_renamer_widget.py",
    Path("gui") / "movie_renamer_view.py",
    Path("gui") / "movie_renamer_table_controller.py",
    Path("gui") / "movie_renamer_resolver.py",
    Path("gui") / "movie_renamer_actions.py", Path("gui") / "movie_renamer_search_actions.py", Path("gui") / "movie_renamer_resolve_search.py", Path("gui") / "movie_renamer_table_search.py",
    Path("gui") / "quality_tester_widget.py",
    Path("gui") / "quality_tester_run_dialog.py",
    Path("gui") / "quality_tester_run_config.py",
    Path("gui") / "quality_tester_files.py",
    Path("gui") / "quality_tester_execution.py",
    Path("gui") / "quality_file_compare_dialog.py",
    Path("gui") / "audio_video_matcher_widget.py",
    Path("gui") / "media_info_dialog.py",
    Path("gui") / "media_info_text_builder.py",
    Path("gui") / "changelog_dialog.py",
    Path("gui") / "video_file_input.py",
    Path("gui") / "file_drop_widgets.py",
    Path("gui") / "journal_resume_base.py",
    Path("gui") / "subtitle_widget.py",
    Path("gui") / "subtitle_widget_workers.py",
    Path("gui") / "subtitle_widget_files.py",
    Path("gui") / "rules_audio_tab.py",
    Path("gui") / "rules_audio_tab_sections.py",
    Path("gui") / "rules_audio_tab_channels.py",
    Path("gui") / "rules_audio_tab_state.py",
    Path("worker") / "converter_thread.py",
    Path("worker") / "converter_runtime_builder.py",
    Path("worker") / "converter_run_loop.py",
    Path("worker") / "converter_lifecycle.py",
    Path("worker") / "converter_file_executor.py",
    Path("worker") / "converter_control.py",
    Path("worker") / "dv_processing_pipeline.py",
    Path("worker") / "dv_pipeline_context.py",
    Path("worker") / "dv_encode_command.py",
    Path("worker") / "dv_command_runner.py",
    Path("worker") / "dv_pipeline_stages.py",
    Path("worker") / "worker_contracts.py",
    Path("core") / "json_io.py",
    Path("core") / "online_metadata_cache.py",
    Path("subtitle") / "tool_logging.py",
    Path("worker") / "quality_test_thread.py",
    Path("worker") / "quality_compare_thread.py",
    Path("worker") / "audio_video_match_thread.py",
    Path("worker") / "postprocess_service.py",
    Path("worker") / "trickplay_service.py",
    Path("rules") / "audio_rules.py",
    Path("rules") / "move_rules.py",
    Path("rules") / "move_rule_config.py",
    Path("rules") / "move_series_detection.py",
    Path("rules") / "move_path_helpers.py",
    Path("rules") / "move_series_directories.py",
    Path("rules") / "audio_rule_basics.py",
    Path("rules") / "audio_rule_migration.py",
    Path("rules") / "audio_rule_repository.py",
    Path("rules") / "audio_transcode_policy.py",
    Path("rules") / "audio_selection.py",
    Path("rules") / "subtitle_rule_config.py",
    Path("rules") / "subtitle_rules.py",
    Path("rules") / "subtitle_plan_models.py",
    Path("rules") / "subtitle_selection.py",
    Path("rules") / "subtitle_keep_policy.py",
    Path("rules") / "subtitle_burn_policy.py",
    Path("rules") / "subtitle_storage.py",
)


def _check_python_package_smoke(root: Path, title: str = "Python-Paket-Smoke-Test") -> ReleaseCheck:
    package_dir = root / "dragontools"
    if not package_dir.exists():
        return ReleaseCheck("error", title, f"Nicht gefunden: {package_dir}")

    missing: list[str] = []
    for name in _PACKAGE_DIRS:
        if not (package_dir / name).is_dir():
            missing.append(f"Ordner fehlt: dragontools/{name}")
    for rel in _SMOKE_MODULES:
        path = package_dir / rel
        if not path.is_file():
            missing.append(f"Modul fehlt: dragontools/{rel.as_posix()}")

    if missing:
        return ReleaseCheck("error", title, "; ".join(missing[:6]))

    syntax_errors: list[str] = []
    for rel in _SMOKE_MODULES:
        path = package_dir / rel
        try:
            ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
        except SyntaxError as exc:
            syntax_errors.append(f"dragontools/{rel.as_posix()}: Zeile {exc.lineno}")
        except Exception as exc:
            syntax_errors.append(f"dragontools/{rel.as_posix()}: {exc}")

    if syntax_errors:
        return ReleaseCheck("error", title, "; ".join(syntax_errors[:6]))
    return ReleaseCheck(
        "ok",
        title,
        "Paketstruktur vollständig, Kernmodule lesbar und syntaktisch gültig.",
    )


def _iter_release_text_files(root: Path) -> Iterable[Path]:
    candidates = [
        root / "help.html",
        root / "build_v9.bat",
        root / "build_v9_angepasst.bat",
        root / f"DragonToolsV{APP_VERSION}.spec",
        root / "DragonToolsV9.spec",
    ]
    history = root / "Aenderungshistorie"
    if history.exists():
        candidates.extend(sorted(history.glob("*.txt")))
        candidates.extend(sorted(history.glob("*.json")))
    for path in candidates:
        if path.exists() and path.is_file():
            yield path



def _check_forbidden_release_artifacts(root: Path) -> ReleaseCheck:
    findings = find_forbidden_release_artifacts(root)
    if not findings:
        return ReleaseCheck(
            "ok",
            "Release-Bytecode",
            "Keine Python-Bytecodes oder Test-/Lint-Cacheverzeichnisse gefunden.",
        )
    preview = ", ".join(path.as_posix() for path in findings[:8])
    remaining = len(findings) - min(len(findings), 8)
    if remaining > 0:
        preview += f" (+{remaining} weitere)"
    return ReleaseCheck(
        "error",
        "Release-Bytecode",
        f"{len(findings)} verbotene Bytecode-/Cache-Artefakte gefunden: {preview}",
    )

_PRIVATE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("lokaler Benutzerpfad", re.compile(r"C:\\Users\\[^\\\r\n]+", re.IGNORECASE)),
    ("persönlicher Name", re.compile(r"\bDragon Developer\b|\bDev\b", re.IGNORECASE)),
    ("Arbeitsordner-Pfad", re.compile(r"DragonTools-Projekt", re.IGNORECASE)),
    ("Netzwerk-Medienpfad", re.compile(r"\\\\media-share", re.IGNORECASE)),
    ("temporärer Codex-Pfad", re.compile(r"AppData\\Local\\Temp\\codex-", re.IGNORECASE)),
    ("möglicher API-Key", re.compile(r"(api[_-]?key|read[_-]?access[_-]?token)\s*[:=]\s*['\"][^'\"\s]{8,}", re.IGNORECASE)),
)


def _scan_private_markers(root: Path) -> list[ReleaseCheck]:
    findings: list[ReleaseCheck] = []
    for path in _iter_release_text_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for label, pattern in _PRIVATE_PATTERNS:
            match = pattern.search(text)
            if match:
                findings.append(
                    ReleaseCheck(
                        "warn",
                        f"Datenschutz: {label}",
                        f"{path.relative_to(root)} enthält '{match.group(0)[:80]}'",
                    )
                )
                break
    if not findings:
        findings.append(ReleaseCheck("ok", "Datenschutz-/Release-Check", "Keine offensichtlichen privaten Marker in Release-Textdateien gefunden."))
    return findings


def _find_dist_dir(root: Path, dist_root: Path | None = None) -> Path | None:
    base = dist_root or (root / "dist")
    candidates = [
        base / f"DragonToolsV{APP_VERSION}",
        base / "DragonToolsV9",
    ]
    for path in candidates:
        if path.exists() and path.is_dir():
            return path
    return None
