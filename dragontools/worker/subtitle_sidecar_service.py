# -*- coding: utf-8 -*-
"""Zentraler Export-Dienst fuer externe Untertitel-Sidecars.

Der Service buendelt Dateinamensschema, MP4-Kompatibilitaet, Zusatz-Sidecars,
Text-zu-SRT-Export und strukturierte Fehler. Das Schema ist
``{output_stem}.{lang}{.forced}{.n}{ext}``; Nummern werden nur bei mehreren
Spuren derselben Sprache/Forced-Kombination gesetzt.
"""
from __future__ import annotations

import json
import re
import traceback
from dataclasses import dataclass
from collections import Counter
from pathlib import Path
from typing import Callable

from ..core.lang_codes import lang_iso_tag, sub_codec_to_ext_and_args
from ..core.models import normalize_override_dict
from ..core.media_library_fix_queue import MediaLibraryFixIssue
from .tool_runner import run_tool
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

def safe_lang_tag(language: str | None) -> str:
    """Normalisiert einen Sprach-Tag für Dateinamen.

    Wandelt den Tag in Kleinbuchstaben um und entfernt alle Zeichen
    außer [a-z0-9].  Ergibt einen leeren String wird "und" verwendet.

    Beispiele:
        "deu"       → "deu"
        "de"        → "de"
        "zh-Hant"   → "zhhant"
        None        → "und"
        ""          → "und"
    """
    tag = (language or "und").lower()
    cleaned = re.sub(r"[^a-z0-9]", "", tag)
    return cleaned or "und"


def sidecar_filename(
    base: Path,
    lang: str,
    forced: bool,
    ext: str,
    number: int | None = None,
) -> str:
    """Erzeugt den vollständigen Sidecar-Pfad nach Jellyfin/VLC-Schema.

    Parameters
    ----------
    base : Path
        Output-Stem (Videodatei ohne Suffix), z.B. Path("/films/Film")
    lang : str
        Bereits normalisierter Sprach-Tag (ISO-639-1, lowercase, [a-z0-9])
    forced : bool
        True wenn Sub-Stream als Forced markiert ist
    ext : str
        Dateierweiterung inkl. Punkt, z.B. ".srt"
    number : int | None
        Laufende Nummer für doppelte (lang, forced)-Kombinationen.
        None   → keine Nummerierung (einzige Spur dieser Art)
        1, 2 … → Nummer wird angehängt

    Returns
    -------
    str
        Vollständiger Dateipfad, z.B.:
            "/films/Film.de.srt"
            "/films/Film.de.forced.srt"
            "/films/Film.de.1.srt"
            "/films/Film.de.forced.2.srt"
    """
    forced_part = ".forced" if forced else ""
    num_part = f".{number}" if number is not None else ""
    base_text = str(base)
    if not base.drive:
        base_text = base.as_posix()
    return base_text + f".{lang}{forced_part}{num_part}{ext}"


# ---------------------------------------------------------------------------
# Strukturierte Export-Ergebnisse
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SubtitleExportFailure:
    stream_index: int
    language: str
    codec: str
    reason: str
    output_path: str = ""


@dataclass(frozen=True)
class SubtitleExportResult:
    """Vollstaendiger fachlicher Status eines Sidecar-Exports."""

    planned_stream_indices: tuple[int, ...] = ()
    exported_paths: tuple[str, ...] = ()
    failures: tuple[SubtitleExportFailure, ...] = ()
    aborted: bool = False
    disabled: bool = False

    @property
    def expected_count(self) -> int:
        return len(self.planned_stream_indices)

    @property
    def exported_count(self) -> int:
        return len(self.exported_paths)

    @property
    def complete(self) -> bool:
        return (
            not self.aborted
            and not self.failures
            and self.exported_count >= self.expected_count
        )

    @property
    def ok(self) -> bool:
        return self.complete

    def failure_summary(self) -> str:
        if self.aborted:
            return "Sidecar-Export wurde abgebrochen."
        if self.failures:
            details = "; ".join(
                f"Sub #{item.stream_index}: {item.reason}" for item in self.failures
            )
            return (
                f"Sidecar-Export unvollstaendig "
                f"({self.exported_count}/{self.expected_count}): {details}"
            )
        if self.exported_count != self.expected_count:
            return (
                f"Sidecar-Export unvollstaendig "
                f"({self.exported_count}/{self.expected_count})."
            )
        return ""


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
        self._log = log
        self._worker = worker

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
            ok, failure, was_aborted = self._export_target(input_path, target)
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
            exported.extend(self._export_pgs_ocr_sidecars(
                input_path=input_path,
                output_base=Path(str(output_base)),
                media_info=media_info,
                streams=selection.pgs_srt_streams,
                abort_check=abort_check,
            ))

        return SubtitleExportResult(
            planned_stream_indices=planned,
            exported_paths=tuple(exported),
            failures=tuple(failures),
            aborted=aborted,
        )

    def _export_pgs_ocr_sidecars(
        self, *, input_path: str, output_base: Path, media_info, streams,
        abort_check: "Callable[[], bool] | None" = None,
    ) -> list[str]:
        if self._worker is None or getattr(self._worker, "settings", None) is None or getattr(self._worker, "tools", None) is None:
            self._log("  ⚠️ PGS→SRT übersprungen: Worker-Laufzeit für OCR nicht verfügbar.", "warn")
            return []
        subtitle_streams = list(getattr(media_info, "subtitle_streams", None) or [])
        ordinal_by_index = {int(stream.index): pos + 1 for pos, stream in enumerate(subtitle_streams)}
        selected = list(streams or [])
        keys = [(safe_lang_tag(lang_iso_tag(getattr(stream, "language", None) or "und")), bool(getattr(stream, "forced", False))) for stream in selected]
        counts = Counter(keys)
        cursors: dict[tuple[str, bool], int] = {}
        service = BitmapSubtitleOcrService(
            settings=self._worker.settings, tools=self._worker.tools, log=self._log, worker=self._worker
        )
        exported: list[str] = []
        self._log(f"  🔤 PGS→SRT: OCR für {len(selected)} ausgewählte Spur(en) …", "info")
        for stream, key in zip(selected, keys):
            if abort_check and abort_check():
                break
            lang, forced = key
            number = None
            if counts[key] > 1:
                number = cursors.get(key, 1)
                cursors[key] = number + 1
            target = Path(sidecar_filename(output_base, lang, forced, ".srt", number))
            issue = MediaLibraryFixIssue(
                media_id=0, path=input_path, title=Path(input_path).stem, item_type="video",
                issue_type="bitmap_subtitle_ocr", action="ocr_bitmap_subtitle",
                problem="PGS→SRT Encode-OCR", action_label="PGS→SRT",
                stream_index=int(stream.index), stream_type="subtitle",
                stream_ordinal=ordinal_by_index.get(int(stream.index)),
                codec=str(getattr(stream, "codec", "") or ""),
                language=str(getattr(stream, "language", "") or ""),
                track_title=str(getattr(stream, "title", "") or ""),
                forced=bool(getattr(stream, "forced", False)),
            )
            try:
                result = service.create_srt(issue, target)
            except Exception as exc:
                try:
                    target.unlink(missing_ok=True)
                except OSError:
                    pass
                self._log(
                    f"  ⚠️ PGS→SRT für Sub #{stream.index} übersprungen: {exc}. "
                    "Original-PGS bleibt gemäß Regelwerk erhalten.",
                    "warn",
                )
                continue
            exported.append(str(result))
            self._log(f"  ✅ PGS→SRT erzeugt: {result.name}", "info")
        return exported

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

    def _export_target(self, input_path: str, target) -> tuple[bool, SubtitleExportFailure | None, bool]:
        stream = target.stream
        codec = str(getattr(target, "output_codec", "") or stream.codec or "").lower()
        codec_args = list(getattr(target, "codec_args", ()) or ())
        if not codec_args:  # defensive: planning already filled this case
            codec_result = sub_codec_to_ext_and_args(str(stream.codec or "").lower())
            if codec_result is None:
                return False, self._unsupported_failure(stream, target.language, codec), False
            _ext, codec_args = codec_result
        out_file = Path(target.output_path)
        if out_file.exists() or out_file.is_symlink():
            reason = "Zieldatei existiert bereits; stilles Ueberschreiben blockiert"
            self._log(f"  ⚠️  Sub #{stream.index} ({target.language}): {reason}: {out_file.name}", "warn")
            return False, SubtitleExportFailure(int(stream.index), target.language, codec, reason, target.output_path), False

        completed = run_tool(
            [
                self._ffmpeg_path, "-n", "-nostdin", "-loglevel", "error",
                "-i", input_path, "-map", f"0:{stream.index}", *codec_args, target.output_path,
            ],
            label=f"Untertitel-Sidecar #{stream.index}",
            timeout_s=300,
            worker=self._worker,
            log=self._log,
        )
        if getattr(completed, "aborted", False) is True:
            reason = "Sidecar-Export abgebrochen"
            return False, SubtitleExportFailure(int(stream.index), target.language, codec, reason, target.output_path), True
        if getattr(completed, "timed_out", False) is True:
            reason = "Timeout beim Sidecar-Export"
            self._log(f"  ⚠️  Sub #{stream.index} ({target.language}): {reason}.", "warn")
            return False, SubtitleExportFailure(int(stream.index), target.language, codec, reason, target.output_path), False

        try:
            valid_output = out_file.exists() and out_file.stat().st_size > 0
        except OSError:
            valid_output = False
        if completed.returncode == 0 and valid_output:
            suffix = " (Text→SRT)" if getattr(target, "variant", "") == "text_to_srt" else ""
            self._log(f"  📄 Sidecar OK: {out_file.name}{suffix}", "info")
            return True, None, False

        detail = str(completed.stderr or completed.stdout or "").strip()

        # FFmpeg's raw SUP muxer can reject otherwise extractable Matroska PGS
        # packets (for example around malformed display segments). For MKV PGS
        # sources, fall back to MKVToolNix, which can copy the Matroska track
        # without routing it through FFmpeg's SUP muxer. OCR remains a separate
        # best-effort concern; this fallback protects the original bitmap track.
        if codec in {"hdmv_pgs_subtitle", "pgs"} and Path(input_path).suffix.casefold() == ".mkv":
            if self._try_mkvextract_pgs_fallback(input_path, stream, out_file):
                self._log(
                    f"  📄 Sidecar OK: {out_file.name} (MKVToolNix-Fallback nach FFmpeg-Fehler)",
                    "info",
                )
                return True, None, False

        reason = f"Export fehlgeschlagen (rc={completed.returncode})"
        if detail:
            reason += f": {detail[-500:]}"
        self._log(f"  ⚠️  Sub #{stream.index} ({target.language}, {codec}): {reason}.", "warn")
        return False, SubtitleExportFailure(int(stream.index), target.language, codec, reason, target.output_path), False

    def _try_mkvextract_pgs_fallback(self, input_path: str, stream, out_file: Path) -> bool:
        worker_tools = getattr(self._worker, "tools", None) if self._worker is not None else None
        mkvmerge = str(getattr(worker_tools, "mkvmerge", "") or "").strip()
        mkvextract = str(getattr(worker_tools, "mkvextract", "") or "").strip()
        ffprobe = str(getattr(worker_tools, "ffprobe", "") or "").strip()
        if not mkvmerge or not mkvextract or not ffprobe:
            return False

        try:
            out_file.unlink(missing_ok=True)
        except OSError:
            return False

        probe = run_tool(
            [ffprobe, "-v", "error", "-select_streams", "s", "-show_entries", "stream=index", "-of", "json", input_path],
            label="PGS-Fallback ffprobe", timeout_s=60, worker=self._worker, log=self._log,
        )
        if not probe.ok:
            return False
        try:
            stream_rows = json.loads(probe.stdout or "{}").get("streams") or []
            subtitle_indices = [int(row["index"]) for row in stream_rows if "index" in row]
            subtitle_ordinal = subtitle_indices.index(int(stream.index))
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            return False

        identify = run_tool(
            [mkvmerge, "-J", input_path],
            label="PGS-Fallback mkvmerge identify", timeout_s=60, worker=self._worker, log=self._log,
        )
        if not identify.ok:
            return False
        try:
            tracks = json.loads(identify.stdout or "{}").get("tracks") or []
            subtitle_tracks = [row for row in tracks if str(row.get("type") or "").casefold() == "subtitles"]
            track_id = int(subtitle_tracks[subtitle_ordinal]["id"])
        except (IndexError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return False

        extracted = run_tool(
            [mkvextract, "tracks", input_path, f"{track_id}:{out_file}"],
            label=f"PGS-Sidecar mkvextract #{stream.index}", timeout_s=300, worker=self._worker, log=self._log,
        )
        if getattr(extracted, "aborted", False) or getattr(extracted, "timed_out", False):
            return False
        try:
            return extracted.returncode == 0 and out_file.is_file() and out_file.stat().st_size > 0
        except OSError:
            return False
