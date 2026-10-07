from __future__ import annotations

from pathlib import Path


def _module_paths(package: str, names: str) -> tuple[Path, ...]:
    return tuple(Path(package) / f"{name}.py" for name in names.split())


REFACTOR_SMOKE_MODULES = (
    *_module_paths('core', 'renamer_file_commit renamer_identity_review'),
    *_module_paths('gui', 'qt_receiver_state movie_renamer_browser_mapping movie_renamer_browser_runtime movie_renamer_resolve_runtime'),
    *_module_paths(
        "core",
        "models file_override_normalization media_analyzer_metadata media_analyzer_result media_duration output_timestamps "
        "move_file_service move_preparation move_conflict_transactions move_journal_adapter move_transfer_executor "
        "media_library_path_mappings media_library_series_paths online_metadata_tmdb_resolver "
        "online_metadata_tmdb_suggestions online_metadata_tmdb_transport online_metadata_tvdb_candidates "
        "release_validation_smoke_modules update_check windows_restart_policy "
        "settings_backup_common settings_backup_limits settings_backup_crypto settings_backup_export settings_backup_restore "
        "settings_watch watch_folder quality_target sdr_hdr_enhancement renamer_metadata_browser "
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
        "online_metadata_settings_state watch_folder_controller watch_folder_rule_dialog convert_widget_watch_intake watch_folder_main_window_bridge "
        "convert_widget_encoder_state convert_widget_encoder_panels convert_widget_encoder_controls "
        "convert_widget_encoder_apply move_lifecycle_helpers move_regular_lifecycle move_incremental_lifecycle",
    ),
    *_module_paths(
        "rules",
        "pipeline_selector pipeline_capabilities pipeline_policy audio_plan audio_plan_policy",
    ),
    *_module_paths(
        "worker",
        "tool_runner tool_process_lifecycle move_thread move_runtime_control move_companion_adapter move_result_commit "
        "move_batch_lifecycle move_batch_executor move_completion_service "
        "subtitle_sidecar_service subtitle_sidecar_plan subtitle_sidecar_targets converter_progress converter_media_probe "
        "converter_process_executor converter_progress_parser media_contract media_contract_builder "
        "media_contract_types output_verifier output_probe output_contract_verifier output_verification_archive "
        "dv_remux_components dv_remux_process dv_remux_audio dv_remux_muxers dv_remux_pipeline "
        "dv_remux_output dv_remux_job dv_remux_thread "
        "merge_common merge_analysis merge_plan merge_executor merge_thread "
        "parallel_converter_queue parallel_converter_control parallel_converter_lifecycle "
        "duration_repair_policy duration_repair_archive duration_repair_orchestrator timestamp_diagnostics "
        "hdrplus_helper_services hdrplus_helper_compat "
        "log_dispatch postprocess_async postprocess_runner postprocess_config postprocess_models postprocess_metadata "
        "trickplay_models trickplay_ffmpeg trickplay_commit trickplay_concurrency trickplay_paths "
        "source_visual_check source_visual_models "
        "source_visual_settings source_visual_analysis source_visual_sampling",
    ),
    *_module_paths(
        "core",
        "release_validation_app release_validation_build release_validation_source "
        "audio_video_time_mapping_fit audio_video_time_mapping_edges",
    ),
    *_module_paths(
        "gui",
        "conversion_progress_focus conversion_progress_display settings_sections/automation settings_sections/comfyui_fields",
    ),
    *_module_paths(
        "worker",
        "duration_timestamp_candidate_archive duration_timestamp_candidate_validation "
        "converter_strip_runtime converter_strip_audio converter_strip_subtitles converter_strip_sidecars "
        "converter_audio_args converter_subtitle_args converter_video_filter_args "
        "quality_process_runner quality_metrics_service quality_compare_service quality_test_service quality_target_service quality_target_integration sdr_hdr_runtime "
        "dv_track_preparation_service dv_final_output_service dv_final_metadata_verifier iso_input_processor iso_processor_host_mixin",
    ),
    *_module_paths(
        "core",
        "config_migration profile_manager bitmap_subtitle_ocr episode_replacement_policy gui_error_report job_journal lang_codes "
        "online_metadata_http online_metadata_retry settings_conversion settings_media_library settings_storage tool_paths",
    ),
    *_module_paths(
        "gui",
        "encoder_profile_service profile_manager_dialog rules_dialog rules_dialog_storage bitmap_subtitle_ocr_review conversion_result_service convert_queue_window "
        "convert_widget_queue_reorder_actions file_list_queue_index main_window_menus main_window_shutdown queue_ordering tab_lazy_loading "
        "online_metadata_action_workers",
    ),
    *_module_paths("subtitle", "injector"),
    *_module_paths(
        "worker",
        "media_stream_metadata_guard bitmap_subtitle_ocr_service converter_queue_state converter_thread_state encode_plan_service hdr10_color "
        "parallel_converter_state standard_pipeline_runner workflow_engine workflow_factory workflow_planning_service",
    ),
    # Patch AG: optional external HDR10+ generation remains import-smoke covered
    # even when the external generator executable itself is not installed.
    *_module_paths("core", "hdr10plus_generation comfyui_workflow comfyui_hdr_models"),
    *_module_paths("worker", "hdr10plus_generator_client comfyui_client comfyui_runtime comfyui_video_worker converter_optional_runtime "
                  "hdrplus_pipeline_coordinator hdrplus_conversion hdrplus_runtime_models "
                  "dv_dynamic_metadata_service dv_workflow_pipeline_adapter pipeline_decision_service workflow_models"),
    *_module_paths("core", "diagnostic_package"),

    # Patch Q-W modules documented in the public patch history must remain part
    # of the release smoke contract as well.
    *_module_paths("core", "callback_dispatch move_sidecars"),
    *_module_paths("gui", "convert_widget_custom_widgets movie_renamer_job_queue"),
    *_module_paths(
        "worker",
        "converter_static_composition duration_original_timeline_service workflow_duration_repair "
        "duration_timestamp_service duration_repair_service dv_result_contract dv_remux_file_dispatcher "
        "parallel_converter_thread dv5_encode_fallback parallel_worker_launcher",
    ),

    *_module_paths("gui", "utility_worker_start"),
    *_module_paths("core", "online_metadata_identity online_metadata_tvdb_localization online_metadata_tvdb_pagination"),
    *_module_paths("core", "media_library_analysis_merge media_library_scan_analysis media_library_scan_plan media_library_publication media_library_video_flags"),
    *_module_paths("worker", "iso_output_publication iso_title_parser utility_media_analysis utility_output_workspace utility_copy_contract"),
    # All review-added production responsibilities are required source/frozen imports.
    *_module_paths("core",
        "analysis_process audio_sync_validation audio_video_match_identity audio_video_sampling_plan "
        "audio_video_stream_timing comfyui_timing crash_state_files diagnostic_privacy exclusive_text file_update_lock "
        "hdr10plus_json_validation jellyfin_paths job_resume_selection journal_archive journal_runtime "
        "media_library_analysis_merge media_library_publication media_library_scan_analysis media_library_scan_plan "
        "media_library_video_flags media_stream_selection media_track_pairing move_directory_transfer "
        "move_trickplay_transfer online_metadata_identity online_metadata_tvdb_localization "
        "online_metadata_tvdb_pagination owned_process owned_process_pause preflight_metadata_identity process_status "
        "quality_extra_args recovery_file release_archive_commit release_document_privacy release_private_paths "
        "release_requirement_bounds release_source_identity renamer_file_commit renamer_identity_review replace_recovery "
        "rules_preview_context settings_backup_payload sidecar_recovery strict_numbers transaction_identity "
        "watch_folder_observations"
    ),
    *_module_paths("gui",
        "application_worker_sources conversion_queue_admission conversion_run_reporting dialog_ownership "
        "encoder_profile_application encoder_profile_options external_program_launch file_worker_pause log_zoom_window "
        "movie_renamer_browser_mapping movie_renamer_browser_runtime movie_renamer_resolve_runtime qt_receiver_state "
        "quality_worker_lifecycle shutdown_worker_state utility_worker_start watch_folder_intake "
        "watch_folder_queue_ownership"
    ),
    *_module_paths("rules",
        "subtitle_output_plan"
    ),
    *_module_paths("subtitle",
        "matroska_tracks media_verification output_safety tag_edit_verification"
    ),
    *_module_paths("worker",
        "audio_metadata_args audio_video_output_contract bitmap_subtitle_packet_probe comfyui_job_monitor "
        "comfyui_mux_plan comfyui_render_plan comfyui_video_contract converter_progress_eta duration_timestamp_plan "
        "dv_filter_graph dv_level5_values dv_matroska_track_selection dv_mux_input_validation dv_remux_output_paths "
        "dv_remux_transaction_state dv_source_rpu_fallback encode_color_plan hdr10plus_generator_frame_contract "
        "hdr_metadata_file_ownership hdr_metadata_picture_policy hdrplus_mp4_audio_service hdrplus_recovery_archive "
        "hdrplus_source_selection hdrplus_workspace iso_output_publication iso_title_parser live_queue_overrides "
        "owned_probe parallel_child_controls parallel_converter_shutdown parallel_file_control parallel_launch_ownership "
        "parallel_queue_coordination postprocess_metadata_identity postprocess_nfo_ownership postprocess_source_trickplay "
        "quality_output_validation required_sidecar_step subtitle_export_models subtitle_movtext_plan "
        "subtitle_ocr_sidecars subtitle_sidecar_exporter tool_binary_output tool_text_output "
        "trickplay_sprite_verification utility_copy_contract utility_media_analysis utility_output_workspace "
        "verification_control worker_result_accounting"
    ),

    *_module_paths("core", "release_frozen_runtime release_qt_icu"),
    *_module_paths("gui", "release_frozen_widgets preflight_metadata_commands"),
    *_module_paths("core", "move_result movie_identity movie_replacement_preparation"),
    *_module_paths("worker", "dv_source_rpu_check"),
    *_module_paths("worker", "encode_geometry_plan postprocess_lifecycle"),
    *_module_paths("worker", "mp4box_track_args mp4_default_flags mkv_audio_track_args"),

)
