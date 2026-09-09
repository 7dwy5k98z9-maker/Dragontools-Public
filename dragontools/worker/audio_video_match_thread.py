# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import traceback
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from ..core.media_analyzer import analyze_media
from ..core.audio_video_matcher import (
    AudioSyncPlan,
    AudioSyncPlanner,
    AudioVideoMatcher,
    CutMatchResult,
    TimeMappingResult,
    format_seconds,
    image_analysis_backend_label,
)
from ..core.paths import get_tool_paths
from ..core.timeout_settings import get_timeout
from .process_control import terminate_process_tree
from .tool_runner import log_tool_failure, run_tool, run_tool_bytes


class AudioVideoMatchThread(QThread):
    log_line = pyqtSignal(str)
    progress = pyqtSignal(int)
    analysis_ready = pyqtSignal(object)
    cuts_ready = pyqtSignal(object)
    plan_ready = pyqtSignal(object)
    result_ready = pyqtSignal(str)
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(
        self,
        operation: str,
        *,
        source_path: str,
        target_path: str,
        output_path: str = "",
        audio_stream_index: int | None = None,
        mapping_result: TimeMappingResult | None = None,
        cut_ranges_text: str = "",
        cut_results: list[CutMatchResult] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.operation = str(operation or "analyze").lower()
        self.source_path = str(Path(source_path).resolve()) if source_path else ""
        self.target_path = str(Path(target_path).resolve()) if target_path else ""
        self.output_path = str(Path(output_path).resolve()) if output_path else ""
        self.audio_stream_index = audio_stream_index
        self.mapping_result = mapping_result
        self.cut_ranges_text = str(cut_ranges_text or "")
        self.cut_results = list(cut_results or [])
        self.tools = get_tool_paths()
        self.current_process: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self.abort_requested = False
        self.abort_type: str | None = None
        self._progress_value = 0

    def request_abort(self, mode: str = "sofort") -> None:
        self.abort_requested = True
        self.abort_type = mode
        if mode == "sofort":
            terminate_process_tree(
                self,
                self._lock,
                log=self._log,
                attr_name="current_process",
                label="Audio-Video-Matcher",
            )

    def cancel(self) -> None:
        self.request_abort("sofort")

    def run(self) -> None:
        try:
            if self.operation == "analyze":
                self._run_analyze()
            elif self.operation == "refine":
                self._run_refine()
            elif self.operation == "create":
                self._run_create()
            else:
                raise ValueError(f"Unbekannte Operation: {self.operation}")
        except Exception as exc:
            self.log_line.emit("❌ Unbehandelte Ausnahme im Audio-Video-Matcher:")
            self.log_line.emit(traceback.format_exc())
            self.error.emit(str(exc))
        finally:
            self.current_process = None
            self.finished.emit()

    def _set_progress(self, value: int) -> None:
        self._progress_value = max(self._progress_value, max(0, min(100, int(value))))
        self.progress.emit(self._progress_value)

    def _progress_message(self, message: str) -> None:
        self.log_line.emit(f"ℹ️  {message}")
        if "Metadaten" in message:
            self._set_progress(5)
        elif "Landmarke" in message:
            self._set_progress(min(75, self._progress_value + 7))
        elif "Zeitmodell" in message:
            self._set_progress(82)
        elif "Schnittbereich" in message:
            self._set_progress(min(85, self._progress_value + 10))

    def _run_analyze(self) -> None:
        self._require_inputs()
        self.log_line.emit("▶ Audio-Video-Matcher: Analyse startet.")
        self.log_line.emit(f"ℹ️  Bildanalyse: {image_analysis_backend_label()}")
        matcher = AudioVideoMatcher(
            self.tools,
            run_bytes=self._run_binary_stdout,
            progress=self._progress_message,
        )
        result = matcher.analyze(self.source_path, self.target_path)
        self._log_analysis_result(result)
        self.analysis_ready.emit(result)
        self._set_progress(100)

    def _run_refine(self) -> None:
        self._require_inputs()
        if self.mapping_result is None:
            raise RuntimeError("Es liegt noch keine A/B/C-Analyse vor.")
        self.log_line.emit("▶ Schnittbereich-Feinanalyse startet.")
        matcher = AudioVideoMatcher(
            self.tools,
            run_bytes=self._run_binary_stdout,
            progress=self._progress_message,
        )
        cuts = matcher.refine_cut_regions(self.mapping_result, self.cut_ranges_text)
        for cut in cuts:
            label = f"{format_seconds(cut.target_start_s)}-{format_seconds(cut.target_end_s)}"
            status = "OK" if cut.resolved else "nicht lösbar"
            self.log_line.emit(
                f"ℹ️  Schnitt {label}: Quelle {format_seconds(cut.source_start_s)}-"
                f"{format_seconds(cut.source_end_s)} | {status}"
            )
            if cut.warning:
                self.log_line.emit(f"⚠️  {cut.warning}")
        self.cuts_ready.emit(cuts)
        self._set_progress(100)

    def _run_create(self) -> None:
        self._require_inputs()
        if self.mapping_result is None:
            raise RuntimeError("Bitte zuerst analysieren.")
        if not self.output_path:
            raise RuntimeError("Bitte einen Ausgabepfad wählen.")
        output = Path(self.output_path)
        if output.exists():
            raise RuntimeError(f"Ausgabe existiert bereits und wird nicht überschrieben: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)

        planner = AudioSyncPlanner()
        plan = planner.build_plan(
            self.mapping_result,
            audio_stream_index=self.audio_stream_index,
            cut_results=self.cut_results,
        )
        self.plan_ready.emit(plan)
        self._log_plan(plan)
        if plan.blocked:
            raise RuntimeError(plan.block_reason or "Audio-Sync-Plan wurde blockiert.")

        temp_dir = Path(tempfile.mkdtemp(prefix="dt_avmatch_"))
        temp_audio = temp_dir / "german_synced.mka"
        temp_output = temp_dir / f"{output.stem}.mkv"
        try:
            self._set_progress(5)
            self.log_line.emit("ℹ️  Deutsche Audiospur wird angepasst.")
            audio_cmd = self._build_audio_command(plan, temp_audio)
            audio_run = run_tool(
                audio_cmd,
                label="Audio anpassen",
                worker=self,
                log=self._log,
                timeout_s=get_timeout("avmatch_process"),
            )
            if not audio_run.ok:
                log_tool_failure(audio_run, label="Audio anpassen", log=self._log, tool_name="ffmpeg")
                raise RuntimeError("Audio-Anpassung fehlgeschlagen.")
            self._set_progress(65)

            self.log_line.emit("ℹ️  Zielvideo und angepasste Audiospur werden gemuxt.")
            mux_cmd = self._build_mux_command(temp_audio, temp_output)
            mux_run = run_tool(
                mux_cmd,
                label="MKV muxen",
                worker=self,
                log=self._log,
                timeout_s=get_timeout("avmatch_process"),
            )
            if not mux_run.ok:
                log_tool_failure(mux_run, label="MKV muxen", log=self._log, tool_name="ffmpeg")
                raise RuntimeError("Muxing fehlgeschlagen.")
            if not temp_output.exists() or temp_output.stat().st_size <= 0:
                raise RuntimeError("Ausgabedatei wurde nicht erzeugt.")
            self._validate_output(temp_output)
            os.replace(str(temp_output), str(output))
            self._set_progress(100)
            self.log_line.emit(f"✅ Datei erstellt: {output}")
            self.result_ready.emit(str(output))
        finally:
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception as exc:
                self.log_line.emit(f"⚠️  Temporärer Matcher-Ordner konnte nicht gelöscht werden: {exc}")

    def _run_binary_stdout(self, cmd: list[str], timeout_s: int | float | None) -> bytes:
        if self.abort_requested:
            raise RuntimeError("Abgebrochen")
        result = run_tool_bytes(
            cmd,
            label=Path(cmd[0]).name if cmd else "Matcher-Tool",
            timeout_s=timeout_s,
            worker=self,
            log=self._log,
        )
        if result.aborted or self.abort_requested:
            raise RuntimeError("Abgebrochen")
        if result.timed_out:
            raise RuntimeError(f"{Path(cmd[0]).name}: Timeout")
        if not result.ok:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(detail or f"{Path(cmd[0]).name} fehlgeschlagen")
        return result.stdout or b""

    def _build_audio_command(self, plan: AudioSyncPlan, temp_audio: Path) -> list[str]:
        base = [
            str(self.tools.ffmpeg),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            self.source_path,
        ]
        if plan.filter_kind == "filter_complex":
            return [
                *base,
                "-filter_complex",
                plan.filter_graph,
                "-map",
                "[aout]",
                "-vn",
                "-sn",
                "-dn",
                "-c:a",
                plan.target_codec,
                "-b:a",
                plan.target_bitrate,
                str(temp_audio),
            ]
        return [
            *base,
            "-map",
            f"0:{plan.audio_stream_index}",
            "-vn",
            "-sn",
            "-dn",
            "-af",
            plan.filter_graph,
            "-c:a",
            plan.target_codec,
            "-b:a",
            plan.target_bitrate,
            str(temp_audio),
        ]

    def _build_mux_command(self, temp_audio: Path, temp_output: Path) -> list[str]:
        return [
            str(self.tools.ffmpeg),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            self.target_path,
            "-i",
            str(temp_audio),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-map",
            "0:a?",
            "-map",
            "0:s?",
            "-map",
            "0:t?",
            "-map",
            "0:d?",
            "-c",
            "copy",
            "-map_metadata",
            "0",
            "-map_chapters",
            "0",
            "-metadata:s:a:0",
            "language=deu",
            "-disposition:a:0",
            "default",
            str(temp_output),
        ]

    def _validate_output(self, output: Path) -> None:
        try:
            info = analyze_media(str(output), self.tools)
            output_duration = float(info.duration_s or 0.0)
            target_duration = float(self.mapping_result.target_info.duration_s if self.mapping_result else 0.0)
            if output_duration > 0 and target_duration > 0 and abs(output_duration - target_duration) > 2.0:
                raise RuntimeError(
                    f"Ausgabedauer unplausibel: Ziel {target_duration:.1f}s, Ausgabe {output_duration:.1f}s"
                )
            self.log_line.emit(f"✅ Ausgabe geprüft: Dauer {output_duration:.1f}s")
        except RuntimeError:
            raise
        except Exception as exc:
            self.log_line.emit(f"⚠️  Ausgabe konnte nicht vollständig geprüft werden: {exc}")

    def _log(self, message: str, severity: str = "info") -> None:
        prefix = {"error": "❌", "warn": "⚠️", "info": "ℹ️"}.get(severity, "ℹ️")
        self.log_line.emit(f"{prefix} {message}")

    def _require_inputs(self) -> None:
        if not self.source_path or not Path(self.source_path).exists():
            raise RuntimeError("Deutsche Quellvideodatei fehlt.")
        if not self.target_path or not Path(self.target_path).exists():
            raise RuntimeError("Zielvideodatei fehlt.")

    def _log_analysis_result(self, result: TimeMappingResult) -> None:
        mode_label = {
            "A": "Fall A – reiner Offset",
            "B": "Fall B – Offset + lineare Drift",
            "C": "Fall C – unterschiedliche Schnitte",
            "D": "Fehlerfall / kein sicheres Match",
        }.get(result.mode, result.mode)
        self.log_line.emit(f"✅ Analyse abgeschlossen: {mode_label}")
        self.log_line.emit(f"ℹ️  Startoffset: {result.offset_s:+.3f}s")
        self.log_line.emit(f"ℹ️  Geschwindigkeitsfaktor: {result.speed_factor:.8f}")
        self.log_line.emit(f"ℹ️  Drift: {result.drift_s:.3f}s | Modellfehler: {result.residual_error_s:.3f}s")
        self.log_line.emit(f"ℹ️  Match-Sicherheit: {result.confidence_percent:.1f}%")
        self.log_line.emit(
            f"ℹ️  Gemeinsamer Bereich Zielvideo: "
            f"{format_seconds(result.common_start_target_s)}-{format_seconds(result.common_end_target_s)}"
        )
        for warning in result.warnings:
            self.log_line.emit(f"⚠️  {warning}")
        if result.suspect_cut_ranges:
            pretty = "; ".join(
                f"{format_seconds(r.start_s)}-{format_seconds(r.end_s)}"
                for r in result.suspect_cut_ranges
            )
            self.log_line.emit(f"⚠️  Verdächtige Schnittbereiche: {pretty}")

    def _log_plan(self, plan: AudioSyncPlan) -> None:
        if plan.blocked:
            self.log_line.emit(f"❌ Audio-Sync-Plan blockiert: {plan.block_reason}")
            return
        self.log_line.emit(
            f"ℹ️  Audio-Sync-Plan: {len(plan.segments)} Segment(e), "
            f"{plan.target_codec} {plan.target_bitrate}"
        )
        for idx, segment in enumerate(plan.segments, start=1):
            self.log_line.emit(
                f"ℹ️    Segment {idx}: Ziel {format_seconds(segment.target_start_s)}-"
                f"{format_seconds(segment.target_end_s)} → Quelle "
                f"{format_seconds(segment.source_start_s)}-{format_seconds(segment.source_end_s)}"
            )
        for warning in plan.warnings:
            self.log_line.emit(f"⚠️  {warning}")
