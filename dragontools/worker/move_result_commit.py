# -*- coding: utf-8 -*-
"""Service-/Commit-Grenze für ``MoveThread``.

Hier werden die bereits getrennten Move-Services verdrahtet. Destruktive
Dateioperationen bleiben in ``core.move_file_service``; dieses Mixin enthält
nur Adapter, Reporting, Sidecars und den Mediathek-Commit nach erfolgreichem
Move.
"""
from __future__ import annotations

import traceback
from pathlib import Path

from PyQt6.QtCore import QSettings

from ..core.move_file_service import MoveFileService
from ..core.move_journal import MoveJournalWriteError
from ..core.move_postprocess import record_media_library_move
from ..core.move_routing import MoveRouter
from ..core.move_sidecars import MoveSidecarService
from ..core.settings import (
    APP_NAME,
    APP_ORG,
    DEFAULT_NFO_MOVIE_TARGET_NAME,
    DEFAULT_TRICKPLAY_CONFLICT_MODE,
    DEFAULT_TRICKPLAY_ONLY_MISSING,
    SET_KEY_NFO_MOVIE_TARGET_NAME,
    SET_KEY_TRICKPLAY_CONFLICT_MODE,
    SET_KEY_TRICKPLAY_ONLY_MISSING,
)
from .move_completion_service import MoveCompletionService


class MoveResultCommitMixin:
    """Verdrahtet Transfer-, Routing-, Sidecar- und DB-Abschlussdienste."""

    def _attr(self, name: str, default=None):
        try:
            return getattr(self, name, default)
        except RuntimeError:
            return default

    def _file_service(self) -> MoveFileService:
        return MoveFileService(
            conflict_mode=self._attr("conflict_mode", "skip"),
            log=self._log,
            wait=self._wait,
            abort_immediately=lambda: bool(
                self._attr("abort_requested", False) and self._attr("abort_type", None) == "sofort"
            ),
            journal=self._attr("_move_journal", None),
        )

    def _planned_target_for(self, path: str):
        lock = self._attr("_planned_targets_lock", None)
        if lock is None:
            return self._attr("planned_targets", {}).get(path)
        with lock:
            return self.planned_targets.get(path)

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

    def _sidecar_service(self) -> MoveSidecarService:
        file_service = self._file_service()
        trickplay_mode = self._attr("_trickplay_conflict_mode", None)
        if trickplay_mode is None:
            trickplay_mode = self._read_trickplay_conflict_mode()
        return MoveSidecarService(
            filme_path=self._attr("filme_path", ""),
            trickplay_conflict_mode=trickplay_mode,
            nfo_movie_target_name=self._read_nfo_movie_target_name(),
            move_file=file_service.move,
            log=self._log,
            append_report=lambda result, kind, sidecar_type: self._append_move_report(
                result, kind=kind, sidecar_type=sidecar_type
            ),
            set_last_result=lambda result: setattr(self, "_last_move_result", result),
        )

    def _completion_service(self) -> MoveCompletionService:
        return MoveCompletionService(
            journal=self._move_journal,
            move_sidecars=self._move_sidecars,
            record_media_library_move=self._record_media_library_move,
            append_move_report=self._append_move_report,
            log=self._log,
        )

    def _move(self, src, dst_dir, hook=None, *, dest_name: str | None = None):
        service = self._file_service()
        try:
            ok, result = service.move(src, dst_dir, hook=hook, dest_name=dest_name)
            self._last_move_result = result
            return ok
        except MoveJournalWriteError:
            if service.last_result is not None:
                self._last_move_result = service.last_result
            raise
        except Exception:
            if service.last_result is not None:
                self._last_move_result = service.last_result
            self._log(f"❌ Unbehandelte Ausnahme beim Move von {Path(src).name}", "error")
            self._log(traceback.format_exc(), "error")
            return False

    def _move_sidecars(self, video_path: str, target_dir: str) -> dict:
        sidecars = self._attr("_sidecar_outputs_by_video", {}).get(video_path, [])
        return self._sidecar_service().move_sidecars(video_path, target_dir, sidecars)

    def _record_media_library_move(self, source_path: str, move_result: dict | None) -> None:
        record_media_library_move(
            QSettings(APP_ORG, APP_NAME),
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

    @staticmethod
    def _read_trickplay_conflict_mode() -> str:
        settings = QSettings(APP_ORG, APP_NAME)
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

    @staticmethod
    def _read_nfo_movie_target_name() -> str:
        settings = QSettings(APP_ORG, APP_NAME)
        configured = settings.value(
            SET_KEY_NFO_MOVIE_TARGET_NAME,
            DEFAULT_NFO_MOVIE_TARGET_NAME,
            type=str,
        )
        return str(configured or DEFAULT_NFO_MOVIE_TARGET_NAME).strip()
