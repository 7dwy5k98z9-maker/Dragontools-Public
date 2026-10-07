# -*- coding: utf-8 -*-
"""Single-file AudioMux transaction."""
from __future__ import annotations

from pathlib import Path
from .hdrplus_workspace import HDRPlusWorkspace
from .log_dispatch import dispatch_log

from ..core.media_analyzer import analyze_media
from .utility_media_analysis import analyze_owned_media
from ..core.output_replace import commit_staged_output
from ..core.move_transaction import publish_staged_no_replace
from ..core.transaction_identity import path_receipt, receipt_matches


def _fmt_size(num: int) -> str:
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024.0:
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{value:.2f} PB"


class AudioMuxJobRunner:
    def __init__(self, worker, *, planner, verifier) -> None:
        self.worker = worker
        self.planner = planner
        self.verifier = verifier

    def run(self, path: str) -> None:
        w, src = self.worker, Path(path)
        source_receipt = path_receipt(src)
        w.progress_file.emit(path, 0)
        dispatch_log(w.log_line, "")
        dispatch_log(w.log_line, f"Start: {src.name}")
        mi = analyze_owned_media(path, w.tools, worker=w, analyzer=analyze_media)
        if not mi.video_streams:
            return self._fail(path, "Kein Videostream gefunden; AudioMux verarbeitet nur Videodateien.")
        if not mi.audio_streams:
            return self._fail(path, "Keine Audio-Spuren gefunden.")
        if getattr(mi, 'ffmpeg_stream_indices_trusted', True) is False:
            return self._fail(path, "FFmpeg-Streamindizes der Quelle sind nicht bestätigt.")
        dispatch_log(w.log_line, f"Analyse: {mi.analysis_source}")
        dispatch_log(w.log_line, f"Video-Spuren: {len(mi.video_streams)}")
        dispatch_log(w.log_line, f"Audio-Spuren: {len(mi.audio_streams)}")
        dispatch_log(w.log_line, f"Untertitel: {len(mi.subtitle_streams)}")

        plan = self.planner.build_audio_plan(mi)
        self.log_audio_decisions(plan)
        contract = self.planner.build_expected_contract(path, mi, plan)
        final_out, _legacy_temp_out = self.planner.build_output_path(src, w.overwrite_original)
        workspace = HDRPlusWorkspace(final_out.parent, "dragontools_audio_mux_")
        real_out = workspace.root / "audio_mux.mkv"
        verified_output = False
        published = False
        try:
            cmd = self.planner.build_ffmpeg_cmd(str(src), str(real_out), plan)
            dispatch_log(w.log_line, f"Ausgabe: {real_out.name}")
            return_code = w.run_ffmpeg_with_progress(cmd, float(mi.duration_s or 0.0), path)
            if isinstance(return_code, bool) or not isinstance(return_code, int) or return_code != 0:
                raise RuntimeError(f"AudioMux ffmpeg wurde mit Returncode {return_code} beendet.")
            if w.abort_requested and w.abort_type == "sofort":
                return self._fail(path, "Abgebrochen")
            verification = self.verifier.verify(
                output_path=str(real_out),
                expected_duration_ms=int(float(mi.duration_s or 0.0) * 1000) or None,
                expected_contract=contract,
                expected_chapter_count=getattr(self.planner, 'expected_chapter_count', None),
            )
            if w.abort_requested and w.abort_type == "sofort":
                return self._fail(path, "Abgebrochen")
            if not verification.ok:
                detail = "; ".join(verification.messages) or "unbekannter Validierungsfehler"
                raise RuntimeError(f"AudioMux-Ausgabe nicht valide: {detail}")
            verified_output = True
            staging_receipt = path_receipt(real_out)
            before, after = self._publish_output(src, real_out, final_out, source_receipt, staging_receipt)
            published = True
            workspace.mark_persisted()
            dispatch_log(w.log_line, f"Fertig: {final_out.name} ({_fmt_size(before)} -> {_fmt_size(after)})")
            w.file_result.emit(path, True, str(final_out))
        finally:
            if not verified_output:
                workspace.mark_persisted()
            elif not published:
                dispatch_log(w.log_line, f"AudioMux: geprüftes Zwischenergebnis erhalten: {real_out}")
            workspace.finish()

    def _publish_output(self, source, staging, destination, source_receipt, staging_receipt):
        """Publish only the exact source and output bound to this job."""
        w = self.worker
        if not receipt_matches(source, source_receipt):
            raise OSError("AudioMux-Originalquelle wurde während der Verarbeitung verändert; bleibt erhalten.")
        if w.abort_requested and w.abort_type == "sofort":
            raise RuntimeError("Abgebrochen vor AudioMux-Veröffentlichung")
        before, after = source.stat().st_size, staging.stat().st_size
        if w.overwrite_original:
            commit_staged_output(
                source=source, staging=staging, destination=destination,
                log=lambda message, _level="info": dispatch_log(w.log_line, message), min_size=1,
                abort_check=lambda: bool(w.abort_requested and w.abort_type == "sofort"),
                expected_source_receipt=source_receipt, expected_staging_receipt=staging_receipt,
            )
        else:
            if not receipt_matches(staging, staging_receipt):
                raise OSError("Geprüfte AudioMux-Ausgabe wurde vor Veröffentlichung verändert.")
            publish_staged_no_replace(staging, destination)
        return before, after

    def log_audio_decisions(self, plan) -> None:
        for decision in plan:
            chosen, out_idx = decision.stream, decision.out_idx + 1
            channels, codec = int(chosen.channels or 0), chosen.codec or ""
            if not decision.needs_transcode:
                dispatch_log(self.worker.log_line, f"ℹ️  Audio Spur {out_idx} (#{chosen.index}, {codec}, {channels}ch) → copy")
            else:
                bitrate = int(decision.target_bitrate or 0) // 1000
                dispatch_log(self.worker.log_line, 
                    f"ℹ️  Audio Spur {out_idx} (#{chosen.index}, {codec}, {channels}ch) → "
                    f"{decision.target_codec} {decision.target_channels}ch {bitrate}k"
                )
            for note in getattr(decision, "processing_notes", ()) or ():
                dispatch_log(self.worker.log_line, f"ℹ️  Audio Spur {out_idx}: {note}")

    def _fail(self, path: str, message: str) -> None:
        dispatch_log(self.worker.log_line, message)
        self.worker.file_result.emit(path, False, message)
