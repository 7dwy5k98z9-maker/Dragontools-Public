# -*- coding: utf-8 -*-
"""Service-/Commit-Grenze für ``MoveThread``.

Hier werden die bereits getrennten Move-Services verdrahtet. Destruktive
Dateioperationen bleiben in ``core.move_file_service``; dieses Mixin enthält
nur Adapter, Reporting, Sidecars und den Mediathek-Commit nach erfolgreichem
Move.
"""
from __future__ import annotations

from pathlib import Path
from copy import deepcopy

from ..core.move_file_service import MoveFileService
from ..core.move_journal import MoveJournalWriteError
from ..core.move_postprocess import record_media_library_move
from ..core.move_routing import MoveRouter
from ..core.settings_access import worker_settings_snapshot
from ..core.settings_postprocess import DEFAULT_NFO_MOVIE_TARGET_NAME, DEFAULT_TRICKPLAY_CONFLICT_MODE, DEFAULT_TRICKPLAY_ONLY_MISSING, SET_KEY_NFO_MOVIE_TARGET_NAME, SET_KEY_TRICKPLAY_CONFLICT_MODE, SET_KEY_TRICKPLAY_ONLY_MISSING
from .move_completion_service import MoveCompletionService


class MoveResultCommitMixin:
    """Verdrahtet Transfer-, Routing-, Sidecar- und DB-Abschlussdienste."""

    def _attr(self, name: str, default=None):
        try:
            return getattr(self, name, default)
        except RuntimeError:
            return default

    def _worker_settings(self):
        snapshot = self._attr("_settings_snapshot", None)
        return snapshot if snapshot is not None else worker_settings_snapshot()

    def _file_service(self) -> MoveFileService:
        return MoveFileService(
            conflict_mode=self._attr("conflict_mode", "skip"),
            log=self._log,
            wait=self._wait,
            abort_immediately=lambda: bool(
                self._attr("abort_requested", False) and self._attr("abort_type", None) == "sofort"
            ),
            journal=self._attr("_move_journal", None),
            episode_replacement_mode=self._attr("episode_replacement_mode", "auto"),
            confirm_episode_replacement=lambda payload: bool(
                self._ask(payload).get("replace", False)
            ),
        )

    def _planned_target_for(self, path: str):
        lock = self._attr("_planned_targets_lock", None)
        if lock is None:
            return deepcopy(self._attr("planned_targets", {}).get(path))
        with lock:
            return deepcopy(self.planned_targets.get(path))

    def _router(self) -> MoveRouter:
        return MoveRouter(
            tv_path=self._attr("tv_path", ""),
            anime_path=self._attr("anime_path", ""),
            filme_path=self._attr("filme_path", ""),
            all_video_files=list(self._attr("all_video_files", []) or []),
            planned_target_for=self._planned_target_for,
            ask=lambda payload: self._ask(payload),
            log=self._log,
        )

    def _completion_service(self) -> MoveCompletionService:
        """Create the per-batch completion service used by ``MoveBatchExecutor``.

        The batch lifecycle intentionally owns orchestration only.  Wiring the
        companion commit, media-library update and report callback belongs to
        this result/commit mixin.
        """
        return MoveCompletionService(
            journal=self._attr("_move_journal", None),
            move_sidecars=self._move_sidecars,
            record_media_library_move=self._record_media_library_move,
            append_move_report=self._append_move_report,
            log=self._log,
            planned_target_for=self._planned_target_for,
        )

    def _record_media_library_move(self, source_path: str, move_result: dict | None) -> None:
        record_media_library_move(
            self._worker_settings(),
            source_path=source_path,
            move_result=move_result,
            log=self._log,
        )

    def _append_move_report(
        self,
        result: dict | None,
        *,
        kind: str = "video",
        sidecar_type: str | None = None,
    ) -> None:
        if not result:
            return
        entry = dict(result)
        entry["kind"] = kind
        if sidecar_type:
            entry["sidecar_type"] = sidecar_type
        if not hasattr(self, "_move_report_log"):
            self._move_report_log = []
        self._move_report_log.append(entry)

    def _read_trickplay_conflict_mode(self) -> str:
        settings = self._worker_settings()
        mode = settings.value(SET_KEY_TRICKPLAY_CONFLICT_MODE, "", type=str)
        if mode in {"skip", "overwrite", "backup"}:
            return mode
        only_missing = settings.value(
            SET_KEY_TRICKPLAY_ONLY_MISSING,
            DEFAULT_TRICKPLAY_ONLY_MISSING,
            type=bool,
        )
        mode = "skip" if only_missing else "overwrite"
        return mode if mode in {"skip", "overwrite", "backup"} else DEFAULT_TRICKPLAY_CONFLICT_MODE

    def _read_nfo_movie_target_name(self) -> str:
        settings = self._worker_settings()
        configured = settings.value(
            SET_KEY_NFO_MOVIE_TARGET_NAME,
            DEFAULT_NFO_MOVIE_TARGET_NAME,
            type=str,
        )
        return str(configured or DEFAULT_NFO_MOVIE_TARGET_NAME).strip()
