# -*- coding: utf-8 -*-
"""Sidecar-Export und transaktionaler Sidecar-Commit für MP4-Remux."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..core.sidecar_journal import SidecarJournal
from ..core.sidecar_transaction import SidecarCommitError, SidecarCommitTransaction
from .subtitle_sidecar_service import SubtitleExportResult, SubtitleSidecarService


class MP4RemuxSidecarService:
    def __init__(
        self,
        *,
        ffmpeg_path: str,
        subtitle_rules: dict,
        log: Callable[[str, str], None],
        abort_check: Callable[[], bool],
        worker=None,
    ) -> None:
        self.ffmpeg_path = ffmpeg_path
        self.subtitle_rules = dict(subtitle_rules or {})
        self._log = log
        self._abort_check = abort_check
        self._worker = worker

    def export(
        self,
        input_path: str,
        out_base: str,
        *,
        media_info,
    ) -> SubtitleExportResult:
        service = SubtitleSidecarService(
            ffmpeg_path=self.ffmpeg_path,
            subtitle_rules=self.subtitle_rules,
            log=self._log,
            worker=self._worker,
        )
        return service.export_sidecars_result(
            input_path=input_path,
            output_base=out_base,
            media_info=media_info,
            abort_check=self._abort_check,
            preserve_burn_candidate=True,
            container="mp4",
        )

    def cleanup_generated(self, paths: list[str] | tuple[str, ...]) -> None:
        for raw in paths:
            path = Path(raw)
            try:
                if path.exists() or path.is_symlink():
                    path.unlink()
            except OSError as exc:
                self._log(
                    f"Temporäres Sidecar konnte nicht gelöscht werden: {path.name} - {exc}",
                    "warn",
                )

    def commit(
        self,
        paths: list[str],
        *,
        source_base: Path,
        destination_base: Path,
        video_staging: Path,
        video_destination: Path,
        video_committed: bool = False,
    ) -> SidecarCommitTransaction | None:
        if not paths:
            return None
        transaction = SidecarCommitTransaction(
            paths,
            source_base=source_base,
            destination_base=destination_base,
        )
        journal = SidecarJournal.start(
            video_staging=video_staging,
            video_destination=video_destination,
            records=transaction.prepare_records(),
            video_committed=video_committed,
        )
        setattr(transaction, "_dragontools_journal", journal)
        try:
            transaction.commit()
            journal.set_status("sidecars_committed")
        except SidecarCommitError as exc:
            try:
                transaction.rollback()
            except SidecarCommitError:
                pass
            else:
                journal.finish()
            raise RuntimeError(f"Sidecar-Finalisierung fehlgeschlagen: {exc}") from exc
        for destination, backup in transaction.backup_pairs:
            self._log(
                "Vorhandenes Sidecar wurde nicht gelöscht, sondern gesichert: "
                f"{destination.name} -> {backup.name}",
                "warn",
            )
        return transaction
