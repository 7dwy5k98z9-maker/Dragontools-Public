# -*- coding: utf-8 -*-
"""Ausführung und Commit einer einzelnen normalen MP4-Remux-Datei."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from ..core.output_replace import commit_staged_output
from ..core.move_transaction import publish_staged_no_replace
from ..core.sidecar_transaction import SidecarCommitError, SidecarCommitTransaction
from ..core.transaction_identity import path_receipt, receipt_matches
from ..core.callback_dispatch import best_effort_callback
from .mp4_remux_plan import MP4RemuxPlanner
from .subtitle_sidecar_service import SubtitleExportResult
from .mp4_default_flags import finalize_mp4_defaults


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
        output_verifier=None,
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
        self._output_verifier = output_verifier

    def remux(
        self,
        input_path: str,
        output_path: str,
        media_info,
        *,
        current_index: int,
        total_files: int,
        user_abort_error: type[RuntimeError],
        expected_source_receipt=None,
    ) -> bool:
        if self._output_verifier is None:
            return self._fail(input_path, "MP4-Ausgabeprüfung fehlt; Veröffentlichung ist gesperrt.")
        prepared = self._prepare_plan(input_path, output_path, media_info, expected_source_receipt)
        if prepared is None:
            return False
        plan, source_receipt, reason = prepared
        best_effort_callback(self._logger.file_start,
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

        self._log(f"Analyse: {media_info.analysis_source}", "info")
        self._log(f"MP4-Video-Copy freigegeben: {reason}", "info")

        start_ts = time.time()
        size_before = plan.source.stat().st_size if plan.source.exists() else 0
        remux_complete = False
        preserve_for_recovery = False
        expected_chapter_count: int | None = None
        exported_sidecars: list[str] = []
        sidecar_tx: SidecarCommitTransaction | None = None
        try:
            if hasattr(self._output_verifier, "source_chapter_count"):
                expected_chapter_count = int(self._output_verifier.source_chapter_count(str(plan.source)))
            if not self._render_and_verify(plan, input_path, user_abort_error, expected_chapter_count):
                return False

            staging_receipt = path_receipt(plan.staging)
            preserve_for_recovery = True
            if plan.workspace is not None:
                plan.workspace.mark_verified(plan.staging)
            if not receipt_matches(plan.source, source_receipt):
                return self._fail(input_path, "Originalquelle wurde während der Verarbeitung verändert; bleibt erhalten.")

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

            if self._abort_requested():
                self._rollback_sidecars(sidecar_tx)
                return self._fail(input_path, "Abgebrochen vor finalem MP4-Commit", log_error=False)

            try:
                self._publish_output(plan, source_receipt, staging_receipt)
            except Exception as exc:
                self._rollback_sidecars(sidecar_tx)
                return self._fail(
                    input_path,
                    f"Finales MP4-Replace fehlgeschlagen: {exc}",
                )

            remux_complete = True
            if plan.workspace is not None:
                plan.workspace.published = True
            best_effort_callback(self._finish_sidecars, sidecar_tx, exported_sidecars)
            size_after = plan.destination.stat().st_size if plan.destination.exists() else 0
            best_effort_callback(self._logger.file_done,
                input_path,
                str(plan.destination),
                size_before,
                size_after,
                time.time() - start_ts,
                overwritten=(plan.destination.resolve() == plan.source.resolve()),
                start_ts=start_ts,
            )
            best_effort_callback(self._emit_file_progress, input_path, 100, None)
            self._emit_file_result(input_path, True, str(plan.destination))
            return True
        finally:
            if plan.workspace is not None:
                plan.workspace.__exit__()
            if not remux_complete and preserve_for_recovery:
                best_effort_callback(self._log, f"Geprüftes MP4-Zwischenergebnis bleibt erhalten: {plan.staging}", "warn")
            if not remux_complete and not preserve_for_recovery:
                if plan.workspace is None:
                    self._cleanup_partial(plan.staging)
                    self._cleanup_sidecars(exported_sidecars)

    def _prepare_plan(self, input_path, output_path, media_info, expected_source_receipt):
        source_receipt = expected_source_receipt if expected_source_receipt is not None else path_receipt(input_path)
        if not receipt_matches(input_path, source_receipt):
            self._fail(input_path, "Originalquelle wurde seit der Analyse verändert; bleibt erhalten.")
            return None
        compatible, reason = self._planner.video_compatibility(media_info)
        if not compatible:
            self._fail(input_path, reason)
            return None
        plan = self._planner.build(input_path, output_path, media_info)
        return plan, source_receipt, reason

    def _publish_output(self, plan, source_receipt, staging_receipt):
        if not receipt_matches(plan.source, source_receipt) or not receipt_matches(plan.staging, staging_receipt):
            raise OSError("Quelle oder geprüfte MP4-Ausgabe wurde vor dem Commit verändert.")
        if plan.destination.resolve() == plan.source.resolve():
            commit_staged_output(
                source=plan.source,
                staging=plan.staging,
                destination=plan.destination,
                log=self._log,
                min_size=1,
                abort_check=self._abort_requested,
                expected_source_receipt=source_receipt,
                expected_staging_receipt=staging_receipt,
            )
        else:
            if self._abort_requested():
                raise RuntimeError("Abgebrochen vor finalem MP4-Commit")
            # New outputs must never overwrite a path that appeared
            # after resolve_mp4_output_path() selected the destination.
            publish_staged_no_replace(plan.staging, plan.destination)

    def _render_and_verify(self, plan, input_path, user_abort_error, expected_chapter_count) -> bool:
        """Confirm execution and the media contract before sidecar/commit mutation."""
        try:
            return_code = self._run_ffmpeg(
                list(plan.command),
                plan.duration_s,
                input_path,
            )
        except user_abort_error:
            return self._fail(input_path, "Abgebrochen", log_error=False)
        except Exception as exc:
            self._log(f"MP4-Remux fehlgeschlagen: {exc}", "error")
            return self._fail(input_path, str(exc), log_error=False)

        if isinstance(return_code, bool) or not isinstance(return_code, int) or return_code != 0:
            return self._fail(input_path, f"MP4-Remux ohne bestätigten Tool-Erfolg (Returncode {return_code}).")

        if self._abort_requested():
            return self._fail(input_path, "Abgebrochen", log_error=False)
        if not plan.staging.exists() or plan.staging.stat().st_size <= 0:
            return self._fail(input_path, "Ausgabedatei wurde nicht erzeugt.")

        if self._output_verifier is not None:
            if not self._finalize_metadata(plan, input_path):
                return False
            verification = self._output_verifier.verify(
                output_path=str(plan.staging),
                expected_duration_ms=(int(plan.duration_s * 1000) if plan.duration_s > 0 else None),
                expected_audio_tracks=plan.expected_audio_tracks,
                expected_subtitle_tracks=plan.expected_subtitle_tracks,
                expected_contract=plan.expected_contract,
                expected_chapter_count=expected_chapter_count,
            )
            if not verification.ok:
                details = "; ".join(verification.messages) or "unbekannter Verifikationsfehler"
                return self._fail(input_path, f"MP4-Ausgabevalidierung fehlgeschlagen: {details}")

        return True

    def _finalize_metadata(self, plan, input_path):
        try:
            finalize_mp4_defaults(plan.staging, plan.expected_contract, input_path=input_path,
                abort_check=self._abort_requested)
            return True
        except (OSError, ValueError, RuntimeError) as exc:
            return self._fail(input_path, f'MP4-Spurmetadaten konnten nicht abgeschlossen werden: {exc}')

    def _should_export_sidecars(self) -> bool:
        return self._export_subtitles_enabled and not self._ignore_subtitles

    def _fail(self, input_path: str, message: str, *, log_error: bool = True) -> bool:
        if log_error:
            self._log(message, "error")
        self._emit_file_result(input_path, False, message)
        return False

    def _rollback_sidecars(self, transaction: SidecarCommitTransaction | None) -> bool:
        if transaction is None:
            return True
        try:
            transaction.rollback()
            journal = getattr(transaction, "_dragontools_journal", None)
            if journal is not None:
                journal.finish()
            return True
        except SidecarCommitError as exc:
            self._log(f"Sidecar-Rollback unvollständig: {exc}", "error")
            return False

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
