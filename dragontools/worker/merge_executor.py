"""Ausführung und transaktionaler Output-Commit des lossless MKV-Merge."""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from ..core.timeout_settings import get_timeout
from ..core.move_transaction import publish_staged_no_replace
from ..core.transaction_identity import receipt_matches
from ..core.callback_dispatch import best_effort_callback
from .utility_output_workspace import VerifiedOutputWorkspace
from ..core.media_metadata import normalize_video_codec
from .merge_common import MergeUserAbortError
from .merge_output_verifier import MergeOutputVerifier
from .media_contract import _audio_codec_family, _subtitle_codec_family
from .media_contract_types import ExpectedAudioTrack, ExpectedMediaContract, ExpectedSubtitleTrack
from .tool_runner import run_tool


class MergeExecutorMixin:
    """Führt einen bereits validierten Merge-Plan aus."""

    def _run_lossless_merge(self, plan: dict[str, Any]) -> bool:
        container = plan["target_container"]
        files = list(plan["files"])
        output_path = str(plan["output_path"])

        best_effort_callback(self._logger.file_start,
            1,
            1,
            output_path,
            "merge",
            None,
            "lossless",
            plan["tool"],
            q_label="Modus",
        )
        self.progress.emit(50)
        self.file_progress.emit(output_path, 50, "Merge läuft")

        if container == "mkv":
            return self._merge_mkv_lossless(files, output_path, infos=list(plan.get("infos") or []))

        self._log(f"Kein lossless Merge-Pfad für '.{container}' vorhanden.", "error")
        return False

    def _merge_mkv_lossless(self, files: list[str], output_path: str, *, infos: list[dict[str, Any]] | None = None) -> bool:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        infos = list(infos or [])
        self._require_source_receipts(infos)
        workspace = VerifiedOutputWorkspace(output.parent, self._log, prefix='.__dragontools_merge_')
        temp_output = workspace.root / 'merge.mkv'
        command = [self.tools.mkvmerge, "-o", str(temp_output), files[0]]
        for path in files[1:]:
            command += ["+", path]
        start_ts = time.time()
        total_before = self._input_size(files)
        try:
            if not self._run_merge_tool(command):
                return False
            if not temp_output.exists() or temp_output.stat().st_size <= 0:
                self._log("mkvmerge lieferte keine gültige Ausgabedatei.", "error")
                return False
            if self.abort_requested:
                raise MergeUserAbortError("Abgebrochen")
            if not self._verify_merge_output(temp_output, infos):
                return False
            workspace.mark_verified(temp_output)
            if self.abort_requested:
                raise MergeUserAbortError("Abgebrochen")
            self._require_source_receipts(infos)
            if not receipt_matches(temp_output, workspace.verified[temp_output]):
                raise OSError("Geprüfte Merge-Ausgabe wurde vor Veröffentlichung verändert.")
            try:
                publish_staged_no_replace(temp_output, output)
            except OSError as exc:
                self._log(f"Finales Veröffentlichen fehlgeschlagen; geprüfte Datei bleibt erhalten: {exc}", "error")
                return False
            workspace.published = True
            best_effort_callback(self._logger.file_done,
                files[0], str(output), total_before, output.stat().st_size,
                time.time() - start_ts, overwritten=False, start_ts=start_ts)
            best_effort_callback(self._log, "Lossless MKV-Merge erfolgreich abgeschlossen.", "success")
            return True
        finally:
            workspace.__exit__()

    @staticmethod
    def _require_source_receipts(infos):
        for info in infos:
            receipt = info.get('source_receipt')
            if receipt is not None and not receipt_matches(info['path'], receipt):
                raise OSError("Merge-Quelle wurde seit ihrer Analyse verändert.")

    def _run_merge_tool(self, command):
        result = run_tool(command, label="mkvmerge",
            timeout_s=get_timeout("worker_media_process"), timeout_mode="inactivity",
            worker=self, log=self._log, merge_stderr=True,
            stdout_line=lambda line: self._log(f"mkvmerge: {line}") if line.strip() else None)
        if result.aborted or self.abort_requested:
            raise MergeUserAbortError("Abgebrochen")
        if result.timed_out:
            self._log("mkvmerge wurde wegen Inaktivitäts-Timeout abgebrochen.", "error")
            return False
        if type(result.returncode) is not int or result.returncode not in (0, 1):
            self._log(f"mkvmerge fehlgeschlagen (Exitcode {result.returncode}).", "error")
            return False
        if result.returncode == 1:
            best_effort_callback(self._log,
                "mkvmerge meldete Warnungen; die Ausgabe muss vollständig geprüft werden.", "warn")
        return True

    def _verify_merge_output(self, output: Path, infos: list[dict[str, Any]]) -> bool:
        if not infos:
            self._log("Merge-Ausgabeprüfung benötigt den analysierten Eingabeplan.", "error")
            return False
        expected_duration_s = sum(max(0.0, float(info.get("duration_s") or 0.0)) for info in infos)
        contract = self._preservation_contract(infos)
        verifier = MergeOutputVerifier(ffprobe_path=str(self.tools.ffprobe), worker=self)
        result = verifier.verify(
            output_path=str(output),
            expected_duration_ms=(int(expected_duration_s * 1000) if expected_duration_s > 0 else None),
            expected_video_tracks=contract.video_stream_count,
            expected_audio_tracks=contract.audio_stream_count,
            expected_subtitle_tracks=contract.subtitle_stream_count,
            expected_contract=contract,
            expected_chapter_count=sum(max(0, int(info.get("chapter_count") or 0)) for info in infos),
        )
        if result.ok:
            return True
        details = "; ".join(result.messages) or "unbekannter Verifikationsfehler"
        self._log(f"Merge-Ausgabevalidierung fehlgeschlagen: {details}", "error")
        return False

    @staticmethod
    def _preservation_contract(infos):
        first = infos[0]
        video_structure = list(first.get("video_structure") or [])
        audio_structure = list(first.get("audio_structure") or [])
        subtitle_structure = list(first.get("subtitle_structure") or [])
        primary_video = video_structure[0] if video_structure else {}
        dynamic_hdr = first.get("dynamic_hdr") or {}
        return ExpectedMediaContract(
            container="mkv",
            video_codec=normalize_video_codec(primary_video.get("codec") or first.get("video_codec") or ""),
            video_stream_count=max(1, len(video_structure)),
            audio_tracks=tuple(
                ExpectedAudioTrack(
                    codec=_audio_codec_family(track.get("codec")),
                    channels=int(track.get("channels") or 0),
                    language=str(track.get("language") or ""),
                    default=bool(track.get("default", False)),
                    title=str(track.get("title") or ""),
                    forced=bool(track.get("forced", False)),
                )
                for track in audio_structure
            ),
            subtitle_tracks=tuple(
                ExpectedSubtitleTrack(
                    codec=_subtitle_codec_family(track.get("codec")),
                    language=str(track.get("language") or ""),
                    forced=bool(track.get("forced", False)),
                    default=bool(track.get("default", False)),
                    title=str(track.get("title") or ""),
                )
                for track in subtitle_structure
            ),
            require_hdr=bool(dynamic_hdr.get('hdr_format')) or str(primary_video.get('color_transfer') or '').lower() in {'smpte2084', 'pq', 'arib-std-b67', 'hlg'},
            require_dolby_vision=bool(dynamic_hdr.get('dolby_vision')),
            require_hdr10plus=bool(dynamic_hdr.get('hdr10plus')),
            expected_dolby_vision_profile=int(dynamic_hdr.get('dv_profile') or 0) or None,
            min_video_bit_depth=first.get('video_bit_depth'),
            attachment_stream_count=first.get('attachment_count'),
            data_stream_count=first.get('data_count'),
            expected_width=int(primary_video.get("width") or first.get("width") or 0) or None,
            expected_height=int(primary_video.get("height") or first.get("height") or 0) or None,
        )

    def _remove_stale_temp(self, temp_output: Path) -> bool:
        try:
            if temp_output.exists():
                temp_output.unlink()
            return True
        except Exception as exc:
            self._log(
                "Temporäre Merge-Datei konnte nicht entfernt werden "
                f"({temp_output.name}): {exc}",
                "error",
            )
            return False

    def _cleanup_partial_output(self, temp_output: Path) -> None:
        if not temp_output.exists():
            return
        try:
            temp_output.unlink()
            self._log(
                f"Partielle temporäre Merge-Datei entfernt: {temp_output.name}",
                "warn",
            )
        except Exception as exc:
            self._log(
                f"Cleanup-Warnung für temporäre Merge-Datei {temp_output.name}: {exc}",
                "warn",
            )

    @staticmethod
    def _input_size(files: list[str]) -> int:
        total = 0
        for path in files:
            try:
                total += Path(path).stat().st_size
            except OSError:
                pass
        return total
