# -*- coding: utf-8 -*-
"""
dragontools/worker/audio_mux_thread.py

Audio-Mux-Thread: Audio Mux für MKV Remux Dateien
  - Audio: konvertieren (nach Audioregeln, aber ohne Anforderungen an Sprache und Anzahl)
  - Video: unverändert (kein Re-Encoding!)
  - Untertitel: werden kopiert
"""

from __future__ import annotations

import subprocess
import threading
import traceback
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from ..core.media_analyzer import analyze_media
from ..core.paths import get_tool_paths
from ..core.timeout_settings import get_timeout
from ..core.output_replace import commit_staged_output
from ..rules.audio_plan import (
    audio_filter_chain,
    audio_input_args_for_plan,
    compute_audio_track_plan,
)
from .process_control import terminate_process_tree
from .tool_runner import run_tool


def _fmt_size(num: int) -> str:
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024.0:
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{value:.2f} PB"


def _safe_name(path: str) -> str:
    return Path(path).name


class AudioMuxThread(QThread):
    progress_total = pyqtSignal(int)
    progress_file = pyqtSignal(str, int)
    log_line = pyqtSignal(str)
    file_result = pyqtSignal(str, bool, str)
    finished = pyqtSignal()

    def __init__(self, files: list[str], overwrite_original: bool = False, parent=None):
        super().__init__(parent)
        self.files = [str(Path(f).resolve()) for f in files]
        self.overwrite_original = overwrite_original
        self.abort_requested: bool = False
        self.abort_type: str | None = None
        self.current_process: subprocess.Popen[str] | None = None
        self._process_lock = threading.Lock()
        self.tools = get_tool_paths()

    def request_abort(self, mode: str = "sofort") -> None:
        self.abort_requested = True
        self.abort_type = mode
        if mode == "sofort":
            terminate_process_tree(
                self,
                self._process_lock,
                log=lambda msg, level="warn": self.log_line.emit(msg),
                attr_name="current_process",
                label="Audio-Mux",
            )

    def cancel(self) -> None:
        self.request_abort()

    def run(self) -> None:
        total = len(self.files)
        done = 0

        try:
            for path in self.files:
                if self.abort_requested:
                    self.log_line.emit("⚠️ Abbruch angefordert.")
                    break

                try:
                    self._process_file_safe(path)
                except Exception as e:
                    self.log_line.emit(f"❌ Unbehandelte Ausnahme bei {_safe_name(path)}")
                    self.log_line.emit(traceback.format_exc())
                    self.file_result.emit(path, False, str(e))

                done += 1
                pct = int(done / max(total, 1) * 100)
                self.progress_total.emit(pct)

        finally:
            self.current_process = None
            self.finished.emit()

    def _build_output_path(self, src: Path) -> tuple[Path, Path | None]:
        """
        Rückgabe:
          (final_output, temp_output_if_replace)
    
        - overwrite_original=True:
            ffmpeg schreibt erst in eine temporäre MKV-Datei,
            danach wird das Original ersetzt.
        - overwrite_original=False:
            Ausgabe liegt daneben als *_Audiomux.mkv
        """
        if self.overwrite_original:
            final = src if src.suffix.lower() == ".mkv" else src.with_suffix(".mkv")
            if final.exists() and final.resolve() != src.resolve():
                raise RuntimeError(
                    f"Zieldatei existiert bereits und wird nicht überschrieben: {final.name}"
                )
            tmp = src.with_name(f"{src.stem}.__audio_mux_tmp__.mkv")
            n = 1
            while tmp.exists() or tmp.resolve() == src.resolve() or tmp.resolve() == final.resolve():
                tmp = src.with_name(f"{src.stem}.__audio_mux_tmp__{n}.mkv")
                n += 1
            return final, tmp
    
        out = src.with_name(f"{src.stem}_Audiomux.mkv")
        n = 1
        while out.exists() or out.resolve() == src.resolve():
            out = src.with_name(f"{src.stem}_Audiomux_{n}.mkv")
            n += 1
        return out, None

    def _build_audio_plan(self, mi):
        # AudioMux nimmt bewusst ALLE Audio-Streams (apply_language_rules=False)
        # und muxt in MKV (keine MP4-Compat-Einschraenkung). Die Transkodier-
        # entscheidung pro Stream ist identisch mit dem Hauptkonverter.
        return compute_audio_track_plan(
            audio_streams=mi.audio_streams,
            file_override=None,
            container="mkv",
            apply_language_rules=False,
        )

    def _log_audio_decisions(self, plan) -> None:
        for decision in plan:
            chosen = decision.stream
            out_idx = decision.out_idx + 1  # 1-basiert fürs Log
            ch = int(chosen.channels or 0)
            src_codec = chosen.codec or ""

            if not decision.needs_transcode:
                self.log_line.emit(
                    f"ℹ️  Audio Spur {out_idx} (#{chosen.index}, {src_codec}, {ch}ch) → copy"
                )
            else:
                tgt_bitrate = int(decision.target_bitrate or 0) // 1000
                self.log_line.emit(
                    f"ℹ️  Audio Spur {out_idx} (#{chosen.index}, {src_codec}, {ch}ch) "
                    f"→ {decision.target_codec} {decision.target_channels}ch {tgt_bitrate}k"
                )
            for note in getattr(decision, "processing_notes", ()) or ():
                self.log_line.emit(f"ℹ️  Audio Spur {out_idx}: {note}")

    def _build_ffmpeg_cmd(self, src: str, out: str, plan) -> list[str]:
        cmd: list[str] = [
            str(self.tools.ffmpeg),
            "-n",
            *audio_input_args_for_plan(plan),
            "-i", src,
            "-map_metadata", "0",
            "-map_chapters", "0",
            "-map", "0:v?",
            "-c:v", "copy",
        ]

        for decision in plan:
            chosen = decision.stream
            out_idx = decision.out_idx
            cmd += ["-map", f"0:{chosen.index}"]

            if not decision.needs_transcode:
                cmd += [f"-c:a:{out_idx}", "copy"]
                continue

            bitrate_k = max(32, int(decision.target_bitrate / 1000) if decision.target_bitrate else 256)
            cmd += [f"-c:a:{out_idx}", decision.target_codec]
            cmd += [f"-b:a:{out_idx}", f"{bitrate_k}k"]
            cmd += [f"-ac:a:{out_idx}", str(decision.target_channels)]
            filter_chain = audio_filter_chain(decision)
            if filter_chain:
                cmd += [f"-filter:a:{out_idx}", filter_chain]

        # Rest kopieren
        cmd += [
            "-map", "0:s?",
            "-c:s", "copy",
            "-map", "0:t?",
            "-c:t", "copy",
            "-map", "0:d?",
            "-c:d", "copy",
            out,
        ]
        return cmd

    def _run_ffmpeg_with_progress(self, cmd: list[str], duration_s: float, path: str) -> int:
        total_us = max(1, int(duration_s * 1_000_000)) if duration_s > 0 else 0
        full = cmd[:-1] + ["-progress", "pipe:1", "-nostats", cmd[-1]]

        def _progress_line(raw: str) -> None:
            line = raw.strip()
            if line.startswith("out_time_ms=") and total_us > 0:
                try:
                    out_us = int(line.split("=", 1)[1].strip())
                    pct = max(0, min(100, int(out_us / total_us * 100)))
                    self.progress_file.emit(path, pct)
                except (TypeError, ValueError):
                    return
            elif line == "progress=end":
                self.progress_file.emit(path, 100)

        result = run_tool(
            full,
            label="Audio-Mux ffmpeg",
            timeout_s=get_timeout("worker_media_process"),
            timeout_mode="inactivity",
            worker=self,
            log=lambda msg, level="info": self.log_line.emit(msg),
            stdout_line=_progress_line,
        )
        if result.aborted:
            return result.returncode
        if result.timed_out:
            raise RuntimeError("ffmpeg wurde wegen Inaktivitäts-Timeout abgebrochen.")
        if not result.ok:
            raise RuntimeError(result.tail(12) or f"ffmpeg return code {result.returncode}")
        return result.returncode

    def _process_file_safe(self, path: str) -> None:
        src = Path(path)
        self.progress_file.emit(path, 0)
        self.log_line.emit("")
        self.log_line.emit(f"Start: {_safe_name(path)}")

        mi = analyze_media(path, self.tools)
        if not mi.audio_streams:
            msg = "Keine Audio-Spuren gefunden."
            self.log_line.emit(msg)
            self.file_result.emit(path, False, msg)
            return

        self.log_line.emit(f"Analyse: {mi.analysis_source}")
        self.log_line.emit(f"Video-Spuren: {len(mi.video_streams)}")
        self.log_line.emit(f"Audio-Spuren: {len(mi.audio_streams)}")
        self.log_line.emit(f"Untertitel: {len(mi.subtitle_streams)}")

        plan = self._build_audio_plan(mi)
        self._log_audio_decisions(plan)

        final_out, temp_out = self._build_output_path(src)
        real_out = temp_out or final_out
        cmd = self._build_ffmpeg_cmd(str(src), str(real_out), plan)

        output_complete = False
        try:
            self.log_line.emit(f"Ausgabe: {real_out.name}")
            self._run_ffmpeg_with_progress(cmd, float(mi.duration_s or 0.0), path)

            if self.abort_requested:
                self.file_result.emit(path, False, "Abgebrochen")
                return

            if not real_out.exists() or real_out.stat().st_size <= 0:
                raise RuntimeError("Ausgabedatei wurde nicht erzeugt.")

            if temp_out is not None:
                backup_size = src.stat().st_size if src.exists() else 0
                tmp_size = real_out.stat().st_size
                if final_out.exists() and final_out.resolve() != src.resolve():
                    raise RuntimeError(
                        f"Zieldatei existiert bereits und wird nicht überschrieben: {final_out.name}"
                    )
                commit_staged_output(
                    source=src,
                    staging=real_out,
                    destination=final_out,
                    log=lambda message, _level="info": self.log_line.emit(message),
                    min_size=1,
                )
                output_complete = True
                final_size = final_out.stat().st_size if final_out.exists() else tmp_size
                self.log_line.emit(
                    f"Fertig: {final_out.name} ({_fmt_size(backup_size)} -> {_fmt_size(final_size)})"
                )
                self.file_result.emit(path, True, str(final_out))
            else:
                output_complete = True
                in_size = src.stat().st_size if src.exists() else 0
                out_size = final_out.stat().st_size
                self.log_line.emit(
                    f"Fertig: {final_out.name} ({_fmt_size(in_size)} -> {_fmt_size(out_size)})"
                )
                self.file_result.emit(path, True, str(final_out))
        finally:
            if not output_complete and real_out.exists():
                try:
                    real_out.unlink()
                except Exception as e:
                    self.log_line.emit(
                        f"Unvollständige AudioMux-Datei konnte nicht gelöscht werden: "
                        f"{real_out.name} - {e}"
                    )
