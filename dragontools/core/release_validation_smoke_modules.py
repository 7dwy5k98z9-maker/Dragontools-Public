from __future__ import annotations

from pathlib import Path


def _module_paths(package: str, names: str) -> tuple[Path, ...]:
    return tuple(Path(package) / f"{name}.py" for name in names.split())


REFACTOR_SMOKE_MODULES = (
    *_module_paths(
        "core",
        "models file_override_normalization media_analyzer_metadata media_analyzer_result "
        "move_file_service move_conflict_transactions move_journal_adapter move_transfer_executor "
        "media_library_path_mappings media_library_series_paths online_metadata_tmdb_resolver "
        "online_metadata_tmdb_suggestions online_metadata_tmdb_transport online_metadata_tvdb_candidates "
        "release_validation_smoke_modules update_check windows_restart_policy "
        "settings_backup_common settings_backup_crypto settings_backup_export settings_backup_restore "
        "job_journal_storage job_journal_resume rules_preview_common rules_preview_audio "
        "rules_preview_subtitles rules_preview_video media_library_item_sql media_library_media_info_mapper "
        "media_library_sqlite media_library_schema media_library_migrations media_library_series_lookup "
        "media_library_jellyfin_source media_library_jellyfin_items media_library_jellyfin_streams "
        "media_library_repository_items media_library_repository_moves media_library_sidecars "
        "media_library_query_fragments media_library_query_scope_filters media_library_query_presets "
        "media_library_search_enrichment media_library_nfo_paths media_library_nfo_parser "
        "media_library_nfo_inventory media_library_nfo_store online_metadata_tvdb_episode_data "
        "media_analyzer_video_streams media_analyzer_audio_streams media_analyzer_subtitle_streams "
        "movie_renamer_candidate_resolvers movie_renamer_candidate_mapping movie_renamer_candidate_scoring "
        "movie_renamer_candidate_order",
    ),
    *_module_paths(
        "gui",
        "update_checker windows_restart_guard media_library_dialog_contracts media_library_dialog_options "
        "media_library_status_tab media_library_mapping_tab media_library_search_tab media_library_sql_tab "
        "drop_path_files drop_path_decode drop_path_windows "
        "preflight_series_view preflight_series_paths preflight_series_metadata "
        "media_library_search_worker preflight_metadata_common preflight_metadata_movie "
        "preflight_metadata_series preflight_metadata_apply "
        "conversion_result_file_events conversion_result_finish conversion_run_finalizer "
        "iso_widget_view iso_widget_inputs iso_widget_runtime "
        "audio_video_matcher_view audio_video_matcher_paths audio_video_matcher_runtime "
        "audio_video_matcher_results online_metadata_dialog_view online_metadata_dialog_state "
        "online_metadata_settings_state "
        "convert_widget_encoder_state convert_widget_encoder_panels convert_widget_encoder_controls "
        "convert_widget_encoder_apply move_lifecycle_helpers move_regular_lifecycle move_incremental_lifecycle",
    ),
    *_module_paths(
        "rules",
        "pipeline_selector pipeline_capabilities pipeline_policy audio_plan audio_plan_policy",
    ),
    *_module_paths(
        "worker",
        "tool_runner tool_process_lifecycle move_thread move_runtime_control move_result_commit "
        "move_batch_lifecycle move_batch_executor move_completion_service "
        "subtitle_sidecar_service subtitle_sidecar_plan subtitle_sidecar_targets converter_progress converter_media_probe "
        "converter_process_executor converter_progress_parser media_contract media_contract_builder "
        "media_contract_types output_verifier output_probe output_contract_verifier "
        "dv_remux_components dv_remux_process dv_remux_audio dv_remux_muxers dv_remux_pipeline "
        "dv_remux_output dv_remux_job dv_remux_thread "
        "merge_common merge_analysis merge_plan merge_executor merge_thread "
        "parallel_converter_queue parallel_converter_control parallel_converter_lifecycle "
        "duration_repair_policy duration_repair_archive duration_repair_orchestrator "
        "hdrplus_helper_services hdrplus_helper_compat "
        "log_dispatch postprocess_async postprocess_runner postprocess_config postprocess_models postprocess_metadata "
        "trickplay_models trickplay_ffmpeg trickplay_commit trickplay_concurrency trickplay_paths "
        "source_visual_check source_visual_models "
        "source_visual_settings source_visual_analysis source_visual_sampling",
    ),
)
