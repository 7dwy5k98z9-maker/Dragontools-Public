# -*- coding: utf-8 -*-
"""Ausführung und Commit einer einzelnen normalen MP4-Remux-Datei."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from ..core.output_replace import commit_staged_output
from ..core.sidecar_transaction import SidecarCommitError, SidecarCommitTransaction
from .mp4_remux_plan import MP4RemuxPlanner
from .subtitle_sidecar_service import SubtitleExportResult


class MP4RemuxFileService:
    """Koordiniert genau eine MP4-Remux-Transaktion ohne Qt-Abhängigkeit."""

    def __init__(
        self,
        *,
        planner: MP4RemuxPlanner,
        logger,
        log: Callable[[str, str], None],
        run_ffmpeg: Callable[[list[str], float, str], int],
        export_sidecars: Callable[..., SubtitleExportResult],
        commit_sidecars: Callable[..., SidecarCommitTransaction | None],
        cleanup_sidecars: Callable[[list[str] | tuple[str, ...]], None],
        abort_requested: Callable[[], bool],
        emit_file_result: Callable[[str, bool, str], None],
        emit_file_progress: Callable[[str, int, object], None],
        export_subtitles: bool,
        ignore_subtitles: bool,
    ) -> None:
        self._planner = planner
        self._logger = logger
        self._log = log
        self._run_ffmpeg = run_ffmpeg
        self._export_sidecars = export_sidecars
        self._commit_sidecars = commit_sidecars
        self._cleanup_sidecars = cleanup_sidecars
        self._abort_requested = abort_requested
        self._emit_file_result = emit_file_result
        self._emit_file_progress = emit_file_progress
        self._export_subtitles_enabled = bool(export_subtitles)
        self._ignore_subtitles = bool(ignore_subtitles)

    def remux(
        self,
        input_path: str,
        output_path: str,
        media_info,
        *,
        current_index: int,
        total_files: int,
        user_abort_error: type[RuntimeError],
    ) -> bool:
        plan = self._planner.build(input_path, output_path, media_info)
        self._logger.file_start(
            current_index,
            total_files,
            input_path,
            "mp4_remux",
            None,
            "copy",
            "mp4_remux",
            q_label="Modus",
        )
        for warning in getattr(media_info, "analysis_warnings", []) or []:
            self._log(f"Analysewarnung: {warning}", "warn")

        compatible, reason = self._planner.video_compatibility(media_info)
        if not compatible:
            return self._fail(input_path, reason)
        self._log(f"Analyse: {media_info.analysis_source}", "info")
        self._log(f"MP4-Video-Copy freigegeben: {reason}", "info")

        start_ts = time.time()
        size_before = plan.source.stat().st_size if plan.source.exists() else 0
        remux_complete = False
        exported_sidecars: list[str] = []
        sidecar_tx: SidecarCommitTransaction | None = None
        try:
            try:
                self._run_ffmpeg(
                    list(plan.command),
                    plan.duration_s,
                    input_path,
                )
            except user_abort_error:
                return self._fail(input_path, "Abgebrochen", log_error=False)
            except Exception as exc:
                self._log(f"MP4-Remux fehlgeschlagen: {exc}", "error")
                return self._fail(input_path, str(exc), log_error=False)

            if self._abort_requested():
                return self._fail(input_path, "Abgebrochen", log_error=False)
            if not plan.staging.exists() or plan.staging.stat().st_size <= 0:
                return self._fail(input_path, "Ausgabedatei wurde nicht erzeugt.")

            if self._should_export_sidecars():
                export_result = self._export_sidecars(
                    input_path,
                    str(plan.staging.with_suffix("")),
                    media_info=media_info,
                )
                exported_sidecars = list(export_result.exported_paths)
                if not export_result.complete:
                    message = export_result.failure_summary() or "Untertitel-Export war unvollständig."
                    return self._fail(input_path, message)
                try:
                    sidecar_tx = self._commit_sidecars(
                        exported_sidecars,
                        source_base=plan.staging.with_suffix(""),
                        destination_base=plan.destination.with_suffix(""),
                        video_staging=plan.staging,
                        video_destination=plan.destination,
                        video_committed=(plan.staging == plan.destination),
                    )
                except RuntimeError as exc:
                    return self._fail(input_path, str(exc))

            if plan.staging != plan.destination:
                try:
                    commit_staged_output(
                        source=plan.source,
                        staging=plan.staging,
                        destination=plan.destination,
                        log=self._log,
                        min_size=1,
                    )
                except Exception as exc:
                    self._rollback_sidecars(sidecar_tx)
                    return self._fail(
                        input_path,
                        f"Finales MP4-Replace fehlgeschlagen: {exc}",
                    )

            remux_complete = True
            self._finish_sidecars(sidecar_tx, exported_sidecars)
            size_after = plan.destination.stat().st_size if plan.destination.exists() else 0
            self._logger.file_done(
                input_path,
                str(plan.destination),
                size_before,
                size_after,
                time.time() - start_ts,
                overwritten=(plan.destination.resolve() == plan.source.resolve()),
                start_ts=start_ts,
            )
            self._emit_file_progress(input_path, 100, None)
            self._emit_file_result(input_path, True, str(plan.destination))
            return True
        finally:
            if not remux_complete:
                self._cleanup_partial(plan.staging)
                self._cleanup_sidecars(exported_sidecars)

    def _should_export_sidecars(self) -> bool:
        return self._export_subtitles_enabled and not self._ignore_subtitles

    def _fail(self, input_path: str, message: str, *, log_error: bool = True) -> bool:
        if log_error:
            self._log(message, "error")
        self._emit_file_result(input_path, False, message)
        return False

    def _rollback_sidecars(self, transaction: SidecarCommitTransaction | None) -> None:
        if transaction is None:
            return
        try:
            transaction.rollback()
            journal = getattr(transaction, "_dragontools_journal", None)
            if journal is not None:
                journal.finish()
        except SidecarCommitError as exc:
            self._log(f"Sidecar-Rollback unvollständig: {exc}", "error")

    def _finish_sidecars(
        self,
        transaction: SidecarCommitTransaction | None,
        exported_paths: list[str],
    ) -> None:
        final_paths = list(transaction.final_paths) if transaction is not None else []
        if transaction is not None:
            journal = getattr(transaction, "_dragontools_journal", None)
            if journal is not None:
                journal.finish()
        for source, destination in zip(exported_paths, final_paths):
            if Path(source) != Path(destination):
                self._log(
                    f"Sidecar verschoben: {Path(source).name} -> {Path(destination).name}",
                    "info",
                )

    def _cleanup_partial(self, staging: Path) -> None:
        if not staging.exists():
            return
        try:
            staging.unlink()
            self._log(f"Partielle Remux-Datei entfernt: {staging.name}", "warn")
        except Exception as exc:
            self._log(
                f"Temporäre Remux-Datei konnte nicht gelöscht werden: {staging.name} - {exc}",
                "warn",
            )
