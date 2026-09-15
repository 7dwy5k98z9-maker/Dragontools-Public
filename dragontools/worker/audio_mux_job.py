# -*- coding: utf-8 -*-
"""Single-file AudioMux transaction."""
from __future__ import annotations

from pathlib import Path

from ..core.media_analyzer import analyze_media
from ..core.output_replace import commit_staged_output


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
        w.progress_file.emit(path, 0)
        w.log_line.emit("")
        w.log_line.emit(f"Start: {src.name}")
        mi = analyze_media(path, w.tools)
        if not mi.video_streams:
            return self._fail(path, "Kein Videostream gefunden; AudioMux verarbeitet nur Videodateien.")
        if not mi.audio_streams:
            return self._fail(path, "Keine Audio-Spuren gefunden.")
        w.log_line.emit(f"Analyse: {mi.analysis_source}")
        w.log_line.emit(f"Video-Spuren: {len(mi.video_streams)}")
        w.log_line.emit(f"Audio-Spuren: {len(mi.audio_streams)}")
        w.log_line.emit(f"Untertitel: {len(mi.subtitle_streams)}")

        plan = self.planner.build_audio_plan(mi)
        self.log_audio_decisions(plan)
        contract = self.planner.build_expected_contract(path, mi, plan)
        final_out, temp_out = self.planner.build_output_path(src, w.overwrite_original)
        real_out = temp_out or final_out
        cmd = self.planner.build_ffmpeg_cmd(str(src), str(real_out), plan)
        output_complete = False
        try:
            w.log_line.emit(f"Ausgabe: {real_out.name}")
            w.run_ffmpeg_with_progress(cmd, float(mi.duration_s or 0.0), path)
            if w.abort_requested and w.abort_type == "sofort":
                return self._fail(path, "Abgebrochen")
            verification = self.verifier.verify(
                output_path=str(real_out),
                expected_duration_ms=int(float(mi.duration_s or 0.0) * 1000) or None,
                expected_contract=contract,
            )
            if not verification.ok:
                detail = "; ".join(verification.messages) or "unbekannter Validierungsfehler"
                raise RuntimeError(f"AudioMux-Ausgabe nicht valide: {detail}")
            if temp_out is not None:
                before = src.stat().st_size if src.exists() else 0
                temp_size = real_out.stat().st_size
                if final_out.exists() and final_out.resolve() != src.resolve():
                    raise RuntimeError(f"Zieldatei existiert bereits und wird nicht überschrieben: {final_out.name}")
                commit_staged_output(
                    source=src, staging=real_out, destination=final_out,
                    log=lambda message, _level="info": w.log_line.emit(message), min_size=1,
                )
                output_complete = True
                after = final_out.stat().st_size if final_out.exists() else temp_size
            else:
                output_complete = True
                before = src.stat().st_size if src.exists() else 0
                after = final_out.stat().st_size
            w.log_line.emit(f"Fertig: {final_out.name} ({_fmt_size(before)} -> {_fmt_size(after)})")
            w.file_result.emit(path, True, str(final_out))
        finally:
            if not output_complete and real_out.exists():
                try:
                    real_out.unlink()
                except OSError as exc:
                    w.log_line.emit(f"Unvollständige AudioMux-Datei konnte nicht gelöscht werden: {real_out.name} - {exc}")

    def log_audio_decisions(self, plan) -> None:
        for decision in plan:
            chosen, out_idx = decision.stream, decision.out_idx + 1
            channels, codec = int(chosen.channels or 0), chosen.codec or ""
            if not decision.needs_transcode:
                self.worker.log_line.emit(f"ℹ️  Audio Spur {out_idx} (#{chosen.index}, {codec}, {channels}ch) → copy")
            else:
                bitrate = int(decision.target_bitrate or 0) // 1000
                self.worker.log_line.emit(
                    f"ℹ️  Audio Spur {out_idx} (#{chosen.index}, {codec}, {channels}ch) → "
                    f"{decision.target_codec} {decision.target_channels}ch {bitrate}k"
                )
            for note in getattr(decision, "processing_notes", ()) or ():
                self.worker.log_line.emit(f"ℹ️  Audio Spur {out_idx}: {note}")

    def _fail(self, path: str, message: str) -> None:
        self.worker.log_line.emit(message)
        self.worker.file_result.emit(path, False, message)
