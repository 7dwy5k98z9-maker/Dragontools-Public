# -*- coding: utf-8 -*-
"""
dragontools/worker/subtitle_sidecar_service.py

Zentraler Export-Dienst für externe Sidecar-Untertiteldateien.

Beide DV-Pipelines – DVProcessingPipeline und DVRemuxThread – verwenden
diese Implementierung. Damit gibt es genau eine massgebliche Logik für:
  - Dateinamensschema
  - globale MP4-Sidecar-Regel / Codec-Kompatibilität
  - Fehlerbehandlung / Rueckgabe als list[str]

Dateinamensschema (Jellyfin/VLC-konform)
-----------------------------------------
  {output_stem}.{lang}{.forced}{.n}{ext}

  lang   : ISO-639-1-Code (2-stellig) aus dem Stream, z.B. "de", "en", "ja".
            Wenn kein 2-stelliger Code bekannt, wird der Originalcode verwendet.
  forced : ".forced" wenn Sub-Stream als Forced markiert ist, sonst leer.
  n      : Laufende Nummer (".1", ".2", …), NUR wenn mehrere Spuren derselben
            Sprache+Forced-Kombination vorhanden sind. Einzelspuren haben
            keine Nummer.
  ext    : Dateierweiterung passend zum Codec (.srt, .ass, .sup, .mks …)

Beispiele:
  Film.de.srt                – eine deutsche Sub (nicht forced)
  Film.de.forced.srt         – eine deutsche forced Sub
  Film.de.1.srt              – erste von mehreren deutschen Subs
  Film.de.2.srt              – zweite von mehreren deutschen Subs
  Film.de.forced.1.srt       – erste von mehreren deutschen forced Subs
  Film.en.srt                – englische Sub
  Film.ja.sup                – japanische PGS-Sub
"""
from __future__ import annotations

import re
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..core.lang_codes import lang_iso_tag, sub_codec_to_ext_and_args
from ..core.models import normalize_override_dict
from .tool_runner import run_tool
from .subtitle_sidecar_plan import build_sidecar_targets, select_sidecar_streams
from ..rules.subtitle_rules import (
    build_mp4_subtitle_storage_plan,
    compute_subtitle_plan,
    mp4_sidecars_enabled,
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
            and self.exported_count == self.expected_count
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
        )
        for warning in getattr(selection.plan, "burn_warnings", ()) or ():
            self._log(f"  ⚠️ {warning}", "warn")

        planned = selection.planned_stream_indices
        if not selection.streams:
            self._log_empty_selection(selection.storage)
            return SubtitleExportResult(planned_stream_indices=planned)

        reason = (
            "globale MP4-Sidecar-Option"
            if mp4_sidecars_enabled(self._subtitle_rules)
            else "MP4-Kompatibilität (PGS/SUP/VobSub)"
        )
        self._log(
            f"  📄 Exportiere {len(selection.streams)} externe Untertitelspur(en) ({reason}) …",
            "info",
        )

        targets, unsupported = build_sidecar_targets(
            selection.streams,
            output_base,
            language_tag=lambda value: safe_lang_tag(lang_iso_tag(value)),
            filename_builder=sidecar_filename,
            codec_resolver=sub_codec_to_ext_and_args,
        )
        failures: list[SubtitleExportFailure] = []
        exported: list[str] = []
        aborted = False

        target_by_index = {int(target.stream.index): target for target in targets}
        unsupported_by_index = {int(stream.index): (stream, language, codec) for stream, language, codec in unsupported}
        for stream in selection.streams:
            if abort_check and abort_check():
                aborted = True
                self._log("  📄 Sidecar-Export nach Abbruch-Signal gestoppt.", "warn")
                break
            target = target_by_index.get(int(stream.index))
            if target is None:
                unsupported_item = unsupported_by_index.get(int(stream.index))
                if unsupported_item is not None:
                    failures.append(self._unsupported_failure(*unsupported_item))
                continue
            ok, failure, was_aborted = self._export_target(input_path, target)
            if ok:
                exported.append(target.output_path)
            if failure is not None:
                failures.append(failure)
            if was_aborted:
                aborted = True
                break

        return SubtitleExportResult(
            planned_stream_indices=planned,
            exported_paths=tuple(exported),
            failures=tuple(failures),
            aborted=aborted,
        )

    def _log_empty_selection(self, storage) -> None:
        if mp4_sidecars_enabled(self._subtitle_rules):
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
        codec = str(stream.codec or "").lower()
        codec_result = sub_codec_to_ext_and_args(codec)
        if codec_result is None:  # defensive: planning already filtered this case
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
            self._log(f"  📄 Sidecar OK: {out_file.name}", "info")
            return True, None, False

        detail = str(completed.stderr or completed.stdout or "").strip()
        reason = f"Export fehlgeschlagen (rc={completed.returncode})"
        if detail:
            reason += f": {detail[-500:]}"
        self._log(f"  ⚠️  Sub #{stream.index} ({target.language}, {codec}): {reason}.", "warn")
        return False, SubtitleExportFailure(int(stream.index), target.language, codec, reason, target.output_path), False
