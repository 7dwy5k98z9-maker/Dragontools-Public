# -*- coding: utf-8 -*-
"""Job restoration and batch-preflight preparation for ConvertWidget."""
from __future__ import annotations

import os
from copy import deepcopy

from ..core.batch_preflight import build_batch_preflight_rows
from ..core.path_syntax import display_name, is_video_file, path_compare_key, to_long_path


class ConvertWidgetRecoveryService:
    """Restore journal entries and build preflight rows without owning the GUI."""

    def __init__(
        self,
        *,
        state,
        file_list,
        log,
        active_worker,
        refresh_queue,
        update_label,
        default_codec: str,
        get_subtitle_rules,
        overwrite_original,
        get_tools,
        get_preview_options=None,
    ) -> None:
        self.state = state
        self.file_list = file_list
        self.log = log
        self.active_worker = active_worker
        self.refresh_queue = refresh_queue
        self.update_label = update_label
        self.default_codec = default_codec
        self.get_subtitle_rules = get_subtitle_rules
        self.overwrite_original = overwrite_original
        self.get_tools = get_tools
        self.get_preview_options = get_preview_options or (lambda: {})

    @staticmethod
    def empty_result() -> dict[str, int]:
        return {"added": 0, "missing": 0, "duplicate": 0, "invalid": 0}

    def restore_job_files(
        self,
        paths: list[str],
        *,
        context: str = "job",
        planned_targets: dict | None = None,
        sidecar_outputs_by_video: dict | None = None,
        target_paths: dict | None = None,
        conflict_mode: str | None = None,
        episode_replacement_mode: str | None = None,
        journal_path: str | None = None,
        companion_resume_sources: dict | None = None,
        file_overrides: dict[str, dict] | None = None,
    ) -> dict[str, int]:
        label = "Move-Wiederaufnahme" if context == "move" else "Job-Wiederaufnahme"
        if bool(getattr(self.state, "start_reserved", False)) or self.active_worker():
            self.log(f"{label} ist während laufender Verarbeitung gesperrt.", "warn")
            return self.empty_result()

        result = self.empty_result()
        for raw_path in paths or []:
            path = str(raw_path or "")
            if not path:
                result["invalid"] += 1
                continue
            if not is_video_file(path):
                result["invalid"] += 1
                self.log(f"{label}: keine Videodatei: {display_name(path)}", "warn")
                continue
            if not os.path.isfile(to_long_path(path)):
                result["missing"] += 1
                self.log(f"{label}: Datei nicht gefunden: {display_name(path)}", "warn")
                continue
            if self.file_list.add_path(path):
                result["added"] += 1
            else:
                result["duplicate"] += 1

        if context == "job" and journal_path:
            self.state.restored_job_journal_path = str(journal_path)

        if context == "job" and isinstance(file_overrides, dict):
            existing_paths = list(self.file_list.get_paths())
            for raw_path, override in file_overrides.items():
                if not isinstance(override, dict):
                    continue
                wanted = path_compare_key(raw_path)
                actual = next(
                    (path for path in existing_paths if path_compare_key(path) == wanted),
                    str(raw_path),
                )
                if actual in existing_paths:
                    self.state.file_overrides[actual] = deepcopy(override)

        if context == "move":
            self._restore_move_context(
                planned_targets=planned_targets,
                sidecar_outputs_by_video=sidecar_outputs_by_video,
                target_paths=target_paths,
                conflict_mode=conflict_mode,
                episode_replacement_mode=episode_replacement_mode,
                journal_path=journal_path,
                companion_resume_sources=companion_resume_sources,
            )

        self.state.total_files = self.file_list.count()
        self.refresh_queue()
        if result["added"]:
            icon = "🚚" if context == "move" else "🔁"
            self.log(f"{icon} {label}: {result['added']} Datei(en) in die Queue geladen.", "info")
        return result

    def _restore_move_context(
        self,
        *,
        planned_targets,
        sidecar_outputs_by_video,
        target_paths,
        conflict_mode,
        episode_replacement_mode,
        journal_path,
        companion_resume_sources,
    ) -> None:
        planned = {
            str(key): deepcopy(value)
            for key, value in (planned_targets or {}).items()
            if str(key or "")
        }
        sidecars = {
            str(key): [str(item) for item in (value or []) if str(item or "")]
            for key, value in (sidecar_outputs_by_video or {}).items()
            if str(key or "")
        }
        self.state.planned_targets.update(planned)
        self.state.sidecar_outputs_by_video.update(sidecars)
        self.state.restored_move_context = {
            "target_paths": dict(target_paths or {}),
            "conflict_mode": str(conflict_mode or ""),
            "episode_replacement_mode": str(episode_replacement_mode or ""),
            "journal_path": str(journal_path or ""),
            "companion_resume_sources": {
                str(key): str(value)
                for key, value in (companion_resume_sources or {}).items()
                if str(key or "") and str(value or "")
            },
        }
        if planned or sidecars or target_paths:
            self.log(
                "🚚 Move-Wiederaufnahme: gespeicherte Ziele, Sidecars und Konfliktregeln übernommen.",
                "info",
            )

    def build_preflight_report_rows(
        self,
        files: list[str],
        planned_targets: dict,
    ) -> list[dict]:
        rows = build_batch_preflight_rows(
            list(files),
            codec=self.default_codec,
            file_overrides=dict(self.state.file_overrides),
            planned_targets=dict(planned_targets),
            subtitle_rules=self.get_subtitle_rules(),
            overwrite_original=bool(self.overwrite_original()),
            filesystem_checks=True,
            tools=self.get_tools(),
            preview_options=dict(self.get_preview_options() or {}),
        )
        self.state.preflight_rows_by_path.update(
            {str(row.get("path")): row for row in rows if row.get("path")}
        )
        for path in files:
            try:
                self.update_label(path)
            except Exception as exc:
                # UI badge refresh is best-effort and must never invalidate a valid preflight,
                # but failures must remain diagnosable.
                self.log(
                    f"Preflight-Badge konnte für {display_name(path)} nicht aktualisiert werden: {exc}",
                    "warn",
                )
                continue
        return rows
