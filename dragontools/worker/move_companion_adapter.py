# -*- coding: utf-8 -*-
"""Companion-first adapters for the move worker.

Keeps destination preparation, NFO/subtitle/trickplay staging and the physical
video transfer out of the bounded result-commit mixin.
"""
from __future__ import annotations

import traceback
from pathlib import Path

from ..core.move_file_service import MoveFileService
from ..core.move_journal import MoveJournalWriteError
from ..core.move_sidecars import MoveSidecarService


class MoveCompanionAdapterMixin:
    """Wire companion-first staging to the existing move services."""

    def _sidecar_service(self) -> MoveSidecarService:
        file_service = self._file_service()
        overwrite_service = MoveFileService(
            conflict_mode="overwrite",
            log=self._log,
            wait=self._wait,
            abort_immediately=lambda: bool(
                self._attr("abort_requested", False)
                and self._attr("abort_type", None) == "sofort"
            ),
            journal=self._attr("_move_journal", None),
            episode_replacement_mode=self._attr("episode_replacement_mode", "auto"),
            confirm_episode_replacement=lambda payload: bool(
                self._ask(payload).get("replace", False)
            ),
        )
        trickplay_mode = self._attr("_trickplay_conflict_mode", None)
        if trickplay_mode is None:
            trickplay_mode = self._read_trickplay_conflict_mode()
        return MoveSidecarService(
            filme_path=self._attr("filme_path", ""),
            trickplay_conflict_mode=trickplay_mode,
            nfo_movie_target_name=self._read_nfo_movie_target_name(),
            move_file=file_service.move,
            overwrite_file=overwrite_service.move,
            log=self._log,
            append_report=lambda result, kind, sidecar_type: self._append_move_report(
                result, kind=kind, sidecar_type=sidecar_type
            ),
            set_last_result=lambda result: setattr(self, "_last_move_result", result),
        )

    def _prepare_move(self, src, dst_dir, *, dest_name: str | None = None) -> dict:
        service = self._file_service()
        prepared = service.prepare_move(src, dst_dir, dest_name=dest_name)
        self._last_move_result = dict(prepared.get("result") or {})
        return prepared

    def _move(
        self,
        src,
        dst_dir,
        hook=None,
        *,
        dest_name: str | None = None,
        prepared: dict | None = None,
        protected_paths: list[str] | tuple[str, ...] | set[str] | None = None,
    ):
        service = self._file_service()
        try:
            ok, result = service.move(
                src,
                dst_dir,
                hook=hook,
                dest_name=dest_name,
                prepared=prepared,
                protected_paths=protected_paths,
            )
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

    def _stage_sidecars_before_video(
        self,
        video_path: str,
        target_dir: str,
        dest_video_path: str,
        source_video_path: str | None = None,
    ) -> dict:
        sidecars = self._attr("_sidecar_outputs_by_video", {}).get(video_path, [])
        return self._sidecar_service().stage_before_video(
            source_video_path or video_path,
            target_dir,
            sidecars,
            dest_video_path=dest_video_path,
        )

    def _rollback_staged_sidecars(self, stage_result: dict | None) -> None:
        self._sidecar_service().rollback_stage(stage_result)

    def _move_sidecars(
        self,
        video_path: str,
        target_dir: str,
        dest_video_path: str | None = None,
        source_video_path: str | None = None,
        staged_paths: list[str] | tuple[str, ...] | set[str] | None = None,
        force_nfo_overwrite: bool = False,
    ) -> dict:
        sidecars = self._attr("_sidecar_outputs_by_video", {}).get(video_path, [])
        return self._sidecar_service().move_sidecars(
            source_video_path or video_path,
            target_dir,
            sidecars,
            dest_video_path=dest_video_path,
            staged_paths=staged_paths,
            force_nfo_overwrite=force_nfo_overwrite,
        )
