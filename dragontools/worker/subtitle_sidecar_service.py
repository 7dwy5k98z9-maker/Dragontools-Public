# -*- coding: utf-8 -*-
"""Zentraler Export-Dienst fuer externe Untertitel-Sidecars.

Der Service buendelt Dateinamensschema, MP4-Kompatibilitaet, Zusatz-Sidecars,
Text-zu-SRT-Export und strukturierte Fehler. Das Schema ist
``{output_stem}.{lang}{.forced}{.n}{ext}``; Nummern werden nur bei mehreren
Spuren derselben Sprache/Forced-Kombination gesetzt.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..core.lang_codes import lang_iso_tag, sub_codec_to_ext_and_args
from ..core.models import normalize_override_dict
from .tool_runner import run_tool
from .log_dispatch import dispatch_log
from .subtitle_export_models import safe_lang_tag, sidecar_filename, SubtitleExportFailure, SubtitleExportResult
from .subtitle_sidecar_exporter import SubtitleSidecarExporter
from .subtitle_ocr_sidecars import export_pgs_ocr_sidecars

from .subtitle_sidecar_plan import select_sidecar_streams
from .subtitle_sidecar_targets import build_sidecar_targets
from .bitmap_subtitle_ocr_service import BitmapSubtitleOcrService
from ..rules.subtitle_rules import (
    additional_sidecars_enabled,
    build_mp4_subtitle_storage_plan,
    compute_subtitle_plan,
    mp4_sidecars_enabled,
    pgs_original_storage,
    pgs_to_srt_enabled,
    text_to_srt_sidecar_enabled,
)


# ---------------------------------------------------------------------------
# Hilfsfunktionen (modulweit, testbar)
# ---------------------------------------------------------------------------





# ---------------------------------------------------------------------------
# Strukturierte Export-Ergebnisse
# ---------------------------------------------------------------------------





# ---------------------------------------------------------------------------
# Zentrale Service-Klasse
# ---------------------------------------------------------------------------

class SubtitleSidecarService:
    """Zentraler Export-Dienst fuer externe Sidecar-Untertitel.

    ``export_sidecars_result()`` ist die produktive API und liefert einen
    strukturierten Vollstaendigkeitsstatus.
    """

    def __init__(
        self,
        *,
        ffmpeg_path: str,
        subtitle_rules: dict,
        log: Callable[[str, str], None],
        worker=None,
    ) -> None:
        self._ffmpeg_path = ffmpeg_path
        self._subtitle_rules = subtitle_rules
        self._log = lambda message, level="info": dispatch_log(log, message, level)
        self._worker = worker

    def _exporter(self):
        return SubtitleSidecarExporter(ffmpeg_path=self._ffmpeg_path, worker=self._worker,
                                       log=self._log, run=run_tool)

    def export_sidecars_result(
        self,
        *,
        input_path: str,
        output_base: "str | Path",
        media_info,
        file_override=None,
        abort_check: "Callable[[], bool] | None" = None,
        preserve_burn_candidate: bool = False,
        container: str = "mp4",
    ) -> SubtitleExportResult:
        """Export all subtitle streams that the MP4 policy requires externally."""
        subtitle_streams = getattr(media_info, "subtitle_streams", None) or []
        if not subtitle_streams:
            self._log("  📄 Keine Untertitelspuren – kein Sidecar-Export.", "info")
            return SubtitleExportResult()

        selection = select_sidecar_streams(
            subtitle_streams,
            audio_streams=getattr(media_info, "audio_streams", None) or [],
            media_duration_s=getattr(media_info, "duration_s", None),
            file_override=file_override,
            subtitle_rules=self._subtitle_rules,
            preserve_burn_candidate=preserve_burn_candidate,
            normalize_override=normalize_override_dict,
            compute_plan=compute_subtitle_plan,
            build_storage_plan=build_mp4_subtitle_storage_plan,
            sidecars_enabled=mp4_sidecars_enabled,
            additional_sidecars_enabled=additional_sidecars_enabled,
            text_to_srt_sidecar_enabled=text_to_srt_sidecar_enabled,
            pgs_to_srt_enabled=pgs_to_srt_enabled,
            pgs_original_storage=pgs_original_storage,
            container=container,
        )
        for warning in getattr(selection.plan, "burn_warnings", ()) or ():
            self._log(f"  ⚠️ {warning}", "warn")

        targets, unsupported = build_sidecar_targets(
            selection.normal_streams,
            output_base,
            ass_srt_streams=selection.ass_srt_streams,
            language_tag=lambda value: safe_lang_tag(lang_iso_tag(value)),
            filename_builder=sidecar_filename,
            codec_resolver=sub_codec_to_ext_and_args,
        )
        planned = (
            tuple(int(target.stream.index) for target in targets)
            + tuple(int(stream.index) for stream, _language, _codec in unsupported)
        )
        if not targets and not unsupported and not getattr(selection, "pgs_srt_streams", ()):
            self._log_empty_selection(selection.storage, container=container)
            return SubtitleExportResult(planned_stream_indices=planned)

        failures: list[SubtitleExportFailure] = []
        exported: list[str] = []
        aborted = False

        if abort_check and abort_check():
            self._log("  📄 Sidecar-Export nach Abbruch-Signal gestoppt.", "warn")
            return SubtitleExportResult(planned_stream_indices=planned, aborted=True)

        reason = self._sidecar_reason(container, selection)
        self._log(
            f"  📄 Exportiere {len(targets)} externe Untertiteldatei(en) ({reason}) …",
            "info",
        )

        for stream, language, codec in unsupported:
            failures.append(self._unsupported_failure(stream, language, codec))

        for target in targets:
            if abort_check and abort_check():
                aborted = True
                self._log("  📄 Sidecar-Export nach Abbruch-Signal gestoppt.", "warn")
                break
            ok, failure, was_aborted = self._export_target(input_path, target, abort_check=abort_check)
            if ok:
                exported.append(target.output_path)
            if failure is not None:
                failures.append(failure)
            if was_aborted:
                aborted = True
                break

        # PGS→SRT is deliberately best-effort. A damaged PGS packet, FFmpeg
        # render error or Tesseract failure must never turn a successful video
        # conversion into a failed file job. The original PGS preservation is
        # handled independently by the normal container/sidecar policy above.
        if not aborted and getattr(selection, "pgs_srt_streams", ()):
            ocr_paths, ocr_aborted = self._export_pgs_ocr_sidecars(
                input_path=input_path,
                output_base=Path(str(output_base)),
                media_info=media_info,
                streams=selection.pgs_srt_streams,
                abort_check=abort_check,
            )
            exported.extend(ocr_paths)
            aborted = aborted or ocr_aborted

        return SubtitleExportResult(
            planned_stream_indices=planned,
            exported_paths=tuple(exported),
            failures=tuple(failures),
            aborted=aborted,
        )

    def _export_pgs_ocr_sidecars(self, *, input_path, output_base, media_info, streams, abort_check=None):
        return export_pgs_ocr_sidecars(input_path=input_path, output_base=output_base,
            media_info=media_info, streams=streams, worker=self._worker, log=self._log,
            abort_check=lambda:self._immediate_abort_requested(abort_check),
            service_factory=BitmapSubtitleOcrService)

    def _immediate_abort_requested(self, abort_check=None) -> bool:
        if abort_check is not None:
            try:
                if bool(abort_check()):
                    return True
            except Exception as exc:
                self._log(f"  ⚠️ Abbruchprüfung für Sidecar-Export fehlgeschlagen: {exc}", "warn")
        worker = self._worker
        if worker is None:
            return False
        state = getattr(worker, "_control_state", None)
        requested = bool(getattr(state, "abort_requested", False)) if state is not None else bool(getattr(worker, "abort_requested", False))
        abort_type = getattr(state, "abort_type", None) if state is not None else getattr(worker, "abort_type", None)
        return bool(requested and abort_type == "sofort")

    def export_mov_text_backup_result(
        self, *, input_path: str, output_base: "str | Path", streams,
        abort_check: "Callable[[], bool] | None" = None,
    ) -> SubtitleExportResult:
        """Sichert mov_text/tx3g nur im Fehlerfall verlustfrei als Subtitle-only-MP4."""
        from .subtitle_movtext_backup import export_mov_text_backup
        return export_mov_text_backup(
            ffmpeg_path=self._ffmpeg_path, input_path=input_path, output_base=output_base,
            streams=streams, abort_check=abort_check, worker=self._worker, log=self._log,
        )

    def _sidecar_reason(self, container: str, selection) -> str:
        target_container = str(container or "mkv").lower()
        reasons: list[str] = []
        if target_container in {"mp4", "m4v", "mov"}:
            if mp4_sidecars_enabled(self._subtitle_rules):
                reasons.append("globale MP4-Sidecar-Option")
            elif getattr(selection, "normal_streams", ()):
                reasons.append("MP4-Kompatibilität (PGS/SUP/VobSub)")
        if additional_sidecars_enabled(self._subtitle_rules):
            reasons.append("zusätzliche Sidecar-Regel")
        if getattr(selection, "ass_srt_streams", ()):
            if text_to_srt_sidecar_enabled(self._subtitle_rules):
                reasons.append("Text-Untertitel zusätzlich als SRT")
        if getattr(selection, "pgs_srt_streams", ()) and pgs_to_srt_enabled(self._subtitle_rules):
            reasons.append("PGS zusätzlich per OCR als SRT")
        return ", ".join(dict.fromkeys(reasons)) or "Regelwerk"

    def _log_empty_selection(self, storage, *, container: str = "mp4") -> None:
        target_container = str(container or "mkv").lower()
        if text_to_srt_sidecar_enabled(self._subtitle_rules):
            self._log("  📄 Keine ausgewählten textbasierten Untertitel für SRT-Sidecars.", "info")
        elif target_container not in {"mp4", "m4v", "mov"}:
            self._log("  📄 Keine zusätzlichen Untertitel-Sidecars gemäß Regelwerk.", "info")
        elif mp4_sidecars_enabled(self._subtitle_rules):
            self._log("  📄 Keine externen MP4-Untertitel gemäß Regelwerk.", "info")
        elif getattr(storage, "internal_streams", ()):
            self._log(
                "  📄 MP4-Sidecars deaktiviert: ausgewählte Text-Untertitel werden intern als mov_text gespeichert.",
                "info",
            )
        else:
            self._log("  📄 Keine MP4-Sidecars erforderlich.", "info")

    def _unsupported_failure(self, stream, language: str, codec: str) -> SubtitleExportFailure:
        reason = f"Codec '{codec or 'unbekannt'}' wird nicht unterstuetzt"
        self._log(f"  ⚠️  Sub #{stream.index} ({codec}, {language}) – {reason}.", "warn")
        return SubtitleExportFailure(int(stream.index), language, codec, reason)

    def _export_target(self, input_path, target, *, abort_check=None):
        return self._exporter().export_target(input_path, target, abort_check=abort_check)

    def _try_mkvextract_pgs_fallback(self, input_path, stream, out_file):
        return self._exporter().pgs_fallback(input_path, stream, out_file)
