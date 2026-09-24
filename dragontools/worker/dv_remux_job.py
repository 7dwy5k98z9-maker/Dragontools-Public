# -*- coding: utf-8 -*-
"""Single-file transaction for the Dolby Vision remux worker."""
from __future__ import annotations

import time
import traceback
from pathlib import Path

from ..core.media_analyzer import analyze_media
from ..core.sidecar_journal import SidecarJournal
from ..core.sidecar_transaction import SidecarCommitError, SidecarCommitTransaction
from ..rules.subtitle_rules import any_sidecar_export_enabled
from .converter_utils import _fd, _fs
from .dv_output_install import DVOutputInstallResult
from .dv_result_contract import emit_dv_failure, mark_dv_terminal
from .worker_events import progress_event, result_event


class DVRemuxJobRunner:
    """Own the complete transaction for one input file.

    The QThread remains responsible for queue/control/lifecycle only.  This
    class owns media analysis, remux execution, sidecar commit/rollback and
    final result signaling.
    """

    def __init__(
        self,
        worker,
        *,
        process_runner,
        pipeline,
        output_manager,
        subtitle_service,
        prepare_metadata=None,
        emit_success=None,
    ):
        self.worker = worker
        self.process_runner = process_runner
        self.pipeline = pipeline
        self.output_manager = output_manager
        self.subtitle_service = subtitle_service
        self.prepare_metadata = prepare_metadata
        self.emit_success = emit_success
        self._prepared_source_trickplay: dict[str, object] = {}

    def run(self, input_path: str) -> bool:
        output_path: str | None = None
        staging_output_path: str | None = None
        remux_complete = False
        video_committed = False
        preserved_output = False
        try:
            self._emit_started(input_path)
            if self.prepare_metadata is not None:
                name, media_info, dur_ms, file_override = self.prepare_metadata(input_path)
            else:
                name, media_info, dur_ms, file_override = self._prepare_metadata(input_path)
            self.worker.log(f"DV-Remux: {name}", "info")

            staging_output_path = self.output_manager.build_output_path(input_path)
            output_path = staging_output_path
            size_before = Path(input_path).stat().st_size if Path(input_path).exists() else 0
            start_ts = time.time()

            if not self.pipeline.run(
                input_path=input_path,
                output_path=output_path,
                mi=media_info,
                dur_ms=dur_ms,
                file_override=file_override,
                name=name,
            ) or self._abort_current_file():
                if not self._abort_current_file():
                    self.worker.log(f"Remux fehlgeschlagen: {name}", "error")
                self._emit_failed(
                    input_path,
                    "DV-Remux-Pipeline fehlgeschlagen oder wurde abgebrochen.",
                    stage="pipeline",
                )
                return False

            verify_output = getattr(self.output_manager, "verify_output", None)
            if callable(verify_output):
                contract = getattr(self.pipeline, "last_expected_contract", None)
                try:
                    verified = verify_output(
                        output_path=output_path, media_info=media_info, expected_duration_ms=dur_ms,
                        expected_contract=contract,
                    )
                except TypeError as exc:
                    if "expected_contract" not in str(exc):
                        raise
                    verified = verify_output(
                        output_path=output_path, media_info=media_info, expected_duration_ms=dur_ms,
                    )
                if not verified:
                    self._emit_failed(
                        input_path,
                        "DV-Remux-Ausgabeverifikation fehlgeschlagen.",
                        stage="verify",
                    )
                    return False

            staged_sidecars = self._export_sidecars_if_needed(
                input_path=input_path,
                output_path=output_path,
                media_info=media_info,
                file_override=file_override,
            )
            if staged_sidecars is None:
                return False
            self._prepare_source_trickplay(input_path)
            if self._abort_current_file():
                self._emit_failed(
                    input_path,
                    "Sofort-Abbruch vor dem destruktiven DV-Commit.",
                    stage="abort_before_commit",
                )
                return False

            sidecar_tx = self._commit_sidecars(input_path, output_path, staged_sidecars)
            if staged_sidecars and sidecar_tx is None:
                return False
            if self._abort_current_file():
                self._rollback_sidecars(sidecar_tx, staged_sidecars)
                self._emit_failed(
                    input_path,
                    "Sofort-Abbruch vor dem Video-Replace; Sidecars wurden zurückgerollt.",
                    stage="abort_before_replace",
                )
                return False

            install = DVOutputInstallResult.from_value(
                self.output_manager.replace_output_if_needed(input_path, output_path)
            )
            output_path = install.output_path
            video_committed = bool(install.committed)
            preserved_output = bool(install.preserved)
            if not install.ok:
                self._rollback_sidecars(sidecar_tx, staged_sidecars)
                self._emit_failed(
                    input_path,
                    "DV-Remux-Ausgabe wurde durch die Größen-/Installationsregel nicht aktiviert.",
                    stage="size_policy" if install.preserved else "replace",
                    output_path=output_path,
                    status="⚠️" if install.preserved else "❌",
                )
                return False

            self._finalize_sidecars(input_path, sidecar_tx)
            if install.cleanup_pending:
                self._run_optional_postprocess(input_path, output_path)
                self._emit_cleanup_pending(
                    input_path, output_path, install.cleanup_message
                )
                return False

            if self._abort_current_file():
                self._emit_failed(
                    input_path,
                    "Sofort-Abbruch wurde während des Video-Commits erkannt; "
                    "die bereits sicher installierte DV-Ausgabe bleibt erhalten.",
                    stage="abort_after_commit",
                    output_path=output_path,
                    status="⚠️",
                )
                return False

            self._run_optional_postprocess(input_path, output_path)
            if self.emit_success is not None:
                self.emit_success(input_path, output_path, name, size_before, start_ts)
            else:
                self._emit_success(input_path, output_path, name, size_before, start_ts)
            remux_complete = True
            return True
        except Exception as exc:
            self.worker.log(
                f"Unbehandelte Ausnahme in DVRemuxJobRunner bei {Path(input_path).name}",
                "error",
            )
            self.worker.log(traceback.format_exc(), "error")
            self._emit_failed(
                input_path,
                f"Unbehandelte Ausnahme im DV-Remux: {exc}",
                stage="unhandled",
                output_path=output_path if video_committed else None,
                status="⚠️" if video_committed else "❌",
            )
            return False
        finally:
            if not remux_complete:
                self._discard_prepared_source_trickplay(input_path, cleanup=False)
                if not video_committed and not preserved_output:
                    self.output_manager.cleanup_incomplete(
                        input_path, staging_output_path or output_path
                    )

    def _abort_current_file(self) -> bool:
        return bool(
            getattr(self.worker, "abort_requested", False)
            and getattr(self.worker, "abort_type", None) == "sofort"
        )

    def _prepare_metadata(self, input_path: str):
        name = Path(input_path).name
        media_info = analyze_media(input_path, self.worker.tools)
        for warning in getattr(media_info, "analysis_warnings", []) or []:
            self.worker.log(f"Analyse-Warnung: {warning}", "warn")
        dur_ms = self.process_runner.probe_ms(input_path)
        file_override = self.worker.file_overrides.get(input_path)
        return name, media_info, dur_ms, file_override

    def _export_sidecars_if_needed(
        self,
        *,
        input_path: str,
        output_path: str,
        media_info,
        file_override: dict | None,
    ) -> list[str] | None:
        w = self.worker
        if any_sidecar_export_enabled(w.subtitle_rules, container=w.container):
            export_result = self.subtitle_service.export_sidecars_result(
                input_path=input_path,
                output_base=Path(output_path).with_suffix(""),
                media_info=media_info,
                file_override=file_override,
                abort_check=self._abort_current_file,
                preserve_burn_candidate=True,
                container=w.container,
            )
            staged = list(export_result.exported_paths)
            if export_result.complete:
                return staged
            self.cleanup_generated_sidecars(staged)
            w.log(
                export_result.failure_summary() or "Sidecar-Export unvollständig.",
                "error",
            )
            self._emit_failed(
                input_path,
                export_result.failure_summary() or "Sidecar-Export unvollständig.",
                stage="sidecar_export",
            )
            return None

        if getattr(media_info, "subtitle_streams", None):
            w.log(
                "  💬 MKV-Ziel: ausgewählte Untertitel sind im Container gespeichert; "
                "kein externer Sidecar-Export.",
                "info",
            )
        return []

    def _prepare_source_trickplay(self, input_path: str) -> None:
        if not bool(getattr(self.worker, "overwrite_original", False)):
            return
        service = getattr(self.worker, "_postprocess_service", None)
        prepare = getattr(service, "prepare_source_trickplay", None) if service is not None else None
        if not callable(prepare):
            return
        final_output = str(Path(input_path).with_suffix(f".{self.worker.container}"))
        self._prepared_source_trickplay[input_path] = prepare(
            input_path=input_path, output_path=final_output
        )

    def _discard_prepared_source_trickplay(self, input_path: str, *, cleanup: bool) -> None:
        self._prepared_source_trickplay.pop(input_path, None)

    def _commit_sidecars(
        self,
        input_path: str,
        output_path: str,
        staged_sidecars: list[str],
    ) -> SidecarCommitTransaction | None:
        if not staged_sidecars:
            return None

        anticipated_output = (
            str(Path(input_path).with_suffix(f".{self.worker.container}"))
            if self.worker.overwrite_original
            else output_path
        )
        try:
            transaction = SidecarCommitTransaction(
                staged_sidecars,
                source_base=Path(output_path).with_suffix(""),
                destination_base=Path(anticipated_output).with_suffix(""),
            )
            journal = SidecarJournal.start(
                video_staging=output_path,
                video_destination=anticipated_output,
                records=transaction.prepare_records(),
                video_committed=(str(Path(output_path)) == str(Path(anticipated_output))),
            )
            setattr(transaction, "_dragontools_journal", journal)
            transaction.commit()
            journal.set_status("sidecars_committed")
            return transaction
        except SidecarCommitError as exc:
            self.cleanup_generated_sidecars(staged_sidecars)
            self.worker.log(f"Sidecar-Finalisierung fehlgeschlagen: {exc}", "error")
            self._emit_failed(
                input_path,
                f"Sidecar-Finalisierung fehlgeschlagen: {exc}",
                stage="sidecar_commit",
            )
            return None

    def _rollback_sidecars(
        self,
        transaction: SidecarCommitTransaction | None,
        staged_sidecars: list[str],
    ) -> None:
        if transaction is not None:
            try:
                transaction.rollback()
                journal = getattr(transaction, "_dragontools_journal", None)
                if journal is not None:
                    journal.finish()
            except SidecarCommitError as exc:
                self.worker.log(f"Sidecar-Rollback unvollständig: {exc}", "error")
        self.cleanup_generated_sidecars(staged_sidecars)

    def _finalize_sidecars(
        self,
        input_path: str,
        transaction: SidecarCommitTransaction | None,
    ) -> None:
        paths = list(transaction.final_paths) if transaction is not None else []
        self.worker._sidecar_outputs[input_path] = paths
        if transaction is None:
            return

        for destination, backup in transaction.backup_pairs:
            self.worker.log(
                "Vorhandenes Sidecar wurde nicht gelöscht, sondern gesichert: "
                f"{destination.name} -> {backup.name}",
                "warn",
            )
        journal = getattr(transaction, "_dragontools_journal", None)
        if journal is not None:
            journal.finish()

    def _run_optional_postprocess(self, input_path: str, output_path: str) -> None:
        """Create NFO/trickplay for direct P7/P8 remuxes as optional companions."""
        service = getattr(self.worker, "_postprocess_service", None)
        if service is None:
            return
        try:
            is_enabled = getattr(service, "is_enabled", None)
            if callable(is_enabled) and not is_enabled():
                return
            prepared_map = getattr(self, "_prepared_source_trickplay", None)
            prepared = prepared_map.pop(input_path, None) if isinstance(prepared_map, dict) else None
            run_kwargs = {"input_path": input_path, "output_path": output_path}
            if prepared is not None:
                run_kwargs["prepared_source_trickplay"] = prepared
            result = service.run_result(**run_kwargs)
            details = [dict(item) for item in (getattr(result, "items", []) or [])]
            created = list(getattr(result, "created_paths", []) or [])
        except Exception as exc:
            details = [{
                "kind": "postprocess",
                "status": "error",
                "path": "",
                "message": str(exc),
            }]
            created = []
            self.worker.log(f"⚠️ Optionales Post-Processing fehlgeschlagen: {exc}", "warn")

        postprocess_outputs = getattr(self.worker, "_postprocess_outputs", None)
        if isinstance(postprocess_outputs, dict):
            postprocess_outputs[input_path] = details

        sidecar_outputs = getattr(self.worker, "_sidecar_outputs", None)
        if isinstance(sidecar_outputs, dict):
            merged = list(sidecar_outputs.get(input_path, []) or [])
            for path in created:
                if path and path not in merged:
                    merged.append(path)
            sidecar_outputs[input_path] = merged

        if any(str(item.get("status", "")).lower() == "error" for item in details):
            self.worker.log(
                f"⚠️ DV-Remux erfolgreich, optionale NFO/Trickplay-Nacharbeit mit Fehlern: {Path(output_path).name}",
                "warn",
            )

    def _emit_started(self, input_path: str) -> None:
        self.worker.worker_event.emit(result_event(input_path, input_path, "⏳"))
        self.worker.file_result.emit(input_path, input_path, "⏳")
        self.worker.worker_event.emit(progress_event(input_path, 0, None))
        self.worker.file_progress.emit(input_path, 0, None)

    def _emit_failed(
        self,
        input_path: str,
        reason: str = "DV-Remux fehlgeschlagen.",
        *,
        stage: str = "dv_remux",
        output_path: str | None = None,
        status: str = "❌",
    ) -> None:
        emit_dv_failure(
            self.worker,
            input_path,
            reason,
            stage=stage,
            output_path=output_path,
            status=status,
        )

    def _emit_cleanup_pending(
        self, input_path: str, output_path: str, message: str
    ) -> None:
        reason = str(
            message
            or "DV-Ausgabe ist installiert; Cleanup des Originals/Backups steht noch aus."
        )
        self.worker.log(f"⚠️ DV-Replace abgeschlossen, Cleanup ausstehend: {Path(input_path).name}", "warn")
        self.worker.log(reason, "warn")
        emit_dv_failure(
            self.worker, input_path, reason, stage="cleanup_pending",
            output_path=output_path, status="⚠️"
        )

    def _emit_success(
        self,
        input_path: str,
        output_path: str,
        name: str,
        size_before: int,
        start_ts: float,
    ) -> None:
        mark_dv_terminal(self.worker, input_path, "✅")
        size_after = Path(output_path).stat().st_size if Path(output_path).exists() else 0
        duration = time.time() - start_ts
        self.worker.log(
            f"✅ {name} → {Path(output_path).name} | "
            f"{_fs(size_before)} → {_fs(size_after)} | {_fd(duration)}",
            "success",
        )
        self.worker.file_progress.emit(input_path, 100, None)
        self.worker.worker_event.emit(progress_event(input_path, 100, None))
        self.worker.worker_event.emit(result_event(input_path, output_path, "✅"))
        self.worker.file_result.emit(input_path, output_path, "✅")

    @staticmethod
    def cleanup_generated_sidecars(paths: list[str] | tuple[str, ...]) -> None:
        for raw in paths:
            path = Path(raw)
            try:
                if path.is_dir() and not path.is_symlink():
                    import shutil
                    shutil.rmtree(path, ignore_errors=True)
                elif path.exists() or path.is_symlink():
                    path.unlink()
            except OSError:
                pass
