"""Shared move result schema, independent of planning and execution."""
from pathlib import Path


def new_move_result(src, dst_dir, *, dest_name: str | None = None) -> dict:
    name = dest_name or Path(src).name
    return {
        "kind": "video", "name": Path(src).name, "source_path": str(src),
        "target_dir": str(dst_dir), "dest_path": str(Path(dst_dir) / name), "ok": False,
        "conflict": False, "deleted_existing": False, "deleted_existing_count": 0,
        "replaced_existing": False, "replaced_existing_count": 0,
        "backed_up_existing": False, "backed_up_existing_count": 0, "renamed": False,
        "skipped_conflict": False, "episode_identity_replacement": False,
        "episode_identity_label": "", "episode_identity_series": "",
        "episode_identity_season": None, "episode_identity_episode": None,
        "replacement_reason": "", "replacement_reminder_required": False,
        "replacement_reminder_id": "", "replacement_artifact_paths": [],
        "replacement_artifact_count": 0,
        "replacement_artifacts_by_type": {"nfo": 0, "trickplay": 0},
        "replacement_artifacts_removed_count": 0,
        "episode_identity_replacement_declined": False,
    }
