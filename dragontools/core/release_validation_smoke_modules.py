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
        "release_validation_smoke_modules update_check windows_restart_policy",
    ),
    *_module_paths(
        "gui",
        "update_checker windows_restart_guard",
    ),
    *_module_paths(
        "rules",
        "pipeline_selector pipeline_capabilities pipeline_policy audio_plan audio_plan_policy",
    ),
    *_module_paths(
        "worker",
        "tool_runner tool_process_lifecycle move_thread move_batch_executor move_completion_service "
        "subtitle_sidecar_service subtitle_sidecar_plan converter_progress converter_media_probe "
        "converter_process_executor converter_progress_parser media_contract media_contract_builder "
        "media_contract_types output_verifier output_probe output_contract_verifier",
    ),
)
