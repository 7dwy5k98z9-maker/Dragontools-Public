# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import subprocess
import threading
import traceback
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from ..core.media_analyzer import analyze_media
from ..core.paths import get_tool_paths
from ..core.quality_tester import (
    QualityMetricResult,
    automatic_quality_segments,
    parse_extra_args,
    parse_quality_segments,
    quality_output_name,
    quality_run_from_dict,
)
from ..core.timeout_settings import get_timeout
from .encoder_args import _scale, _vid_args
from .process_control import terminate_process_tree
from .tool_runner import run_tool


class QualityTestThread(QThread):
    log_line = pyqtSignal(str)
    progress = pyqtSignal(int)
    result_ready = pyqtSignal(object)
    finished = pyqtSignal()

    def __init__(
        self,
        files: list[str],
        output_dir: str,
        runs: list[dict],
        *,
        sample_count: int = 3,
        sample_duration_s: int = 20,
        manual_ranges: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.files = [str(Path(f).resolve()) for f in files]
        self.output_dir = str(Path(output_dir).resolve())
        self.runs = [quality_run_from_dict(r) for r in runs if r]
        self.sample_count = max(1, min(20, int(sample_count or 3)))
        self.sample_duration_s = max(1, int(sample_duration_s or 20))
        self.manual_ranges = str(manual_ranges or "")
        self.tools = get_tool_paths()
        self.current_process: subprocess.Popen | None = None
        self._process_lock = threading.Lock()
        self._abort = False
        self.abort_requested = False
        self.abort_type: str | None = None

    def cancel(self) -> None:
        self._abort = True
        self.abort_requested = True
        self.abort_type = "sofort"
        terminate_process_tree(
            self,
            self._process_lock,
            log=lambda message, _level="warn": self.log_line.emit(message),
            attr_name="current_process",
            label="Qualitätstester-Prozess",
        )

    def run(self) -> None:
        try:
            self._run()
        except Exception:
            self.log_line.emit("❌ Unbehandelte Ausnahme im Qualitätstester:")
            self.log_line.emit(traceback.format_exc())
        finally:
            with self._process_lock:
                self.current_process = None
            self.finished.emit()

    def _run(self) -> None:
        if not self.files:
            self.log_line.emit("⚠️ Keine Dateien im Qualitätstester.")
            return
        if not self.runs:
            self.log_line.emit("⚠️ Keine aktiven Testläufe definiert.")
            return

        out_root = Path(self.output_dir)
        out_root.mkdir(parents=True, exist_ok=True)
        total_units = 0
        file_segments: list[tuple[str, list]] = []
        for file_path in self.files:
            if self._abort:
                return
            mi = analyze_media(file_path, self.tools)
            duration = float(getattr(mi, "duration_s", 0.0) or 0.0)
            segments = parse_quality_segments(
                self.manual_ranges,
                duration_s=duration,
                default_duration_s=float(self.sample_duration_s),
            )
            if not segments:
                segments = automatic_quality_segments(
                    duration_s=duration,
                    count=self.sample_count,
                    segment_duration_s=float(self.sample_duration_s),
                )
            file_segments.append((file_path, segments))
            total_units += len(segments) * len(self.runs)

        done_units = 0
        self.progress.emit(0)
        for file_path, segments in file_segments:
            if self._abort:
                self.log_line.emit("⚠️ Qualitätstest abgebrochen.")
                return
            src = Path(file_path)
            self.log_line.emit(f"▶ Qualitätstest: {src.name}")
            file_out_dir = out_root / src.stem
            file_out_dir.mkdir(parents=True, exist_ok=True)

            for segment in segments:
                for test_run in self.runs:
                    if self._abort:
                        self.log_line.emit("⚠️ Qualitätstest abgebrochen.")
                        return
                    out_path = file_out_dir / quality_output_name(file_path, test_run, segment)
                    self.log_line.emit(
                        f"ℹ️  {test_run.name}: Segment {segment.label} "
                        f"({segment.duration_s:.0f}s ab {segment.start_s:.1f}s)"
                    )
                    try:
                        self._encode_segment(file_path, str(out_path), test_run, segment)
                        result = self._analyze_result(file_path, str(out_path), test_run, segment)
                        self.result_ready.emit(result)
                        self._log_result(result)
                    except Exception as exc:
                        self.log_line.emit(f"❌ Testlauf fehlgeschlagen: {exc}")
                    done_units += 1
                    self.progress.emit(int(done_units / max(total_units, 1) * 100))
        self.progress.emit(100)

    def _run_process(self, cmd: list[str], *, label: str) -> tuple[int, str, str]:
        result = run_tool(
            cmd,
            label=f"Qualitätstest: {label}",
            timeout_s=get_timeout("quality_test_process"),
            worker=self,
            log=lambda message, _level="info": self.log_line.emit(message),
            abort_on_request=True,
        )
        if result.aborted or self._abort:
            raise RuntimeError("Abgebrochen")
        if result.timed_out:
            timeout = result.timeout_s
            if timeout is None:
                raise RuntimeError(f"{label} wurde wegen eines Timeouts beendet.")
            raise RuntimeError(f"{label} Timeout nach {float(timeout):.0f}s.")
        if not result.ok:
            details = result.combined_output
            raise RuntimeError(f"{label} fehlgeschlagen: {details[:2000]}")
        return result.returncode, result.stdout, result.stderr

    def _video_args(self, run) -> list[str]:
        codec = (run.codec or "h265").lower()
        if codec in {"hevc", "x265"}:
            codec = "h265"
        elif codec in {"avc", "x264"}:
            codec = "h264"
        elif codec not in {"h264", "h265", "av1"}:
            codec = "h265"

        encoder = (run.encoder or "cpu").lower()
        if encoder in {"software", "libx264", "libx265", "libsvtav1"}:
            encoder = "cpu"
        elif encoder in {"nvidia", "nvidia nvenc"}:
            encoder = "nvenc"
        elif encoder in {"intel", "intel qsv"}:
            encoder = "qsv"
        elif encoder in {"amd", "amd amf"}:
            encoder = "amf"
        elif encoder not in {"cpu", "nvenc", "qsv", "amf"}:
            encoder = "cpu"

        quality = max(0, min(63, int(run.quality)))
        preset = str(run.preset or ("6" if codec == "av1" and encoder == "cpu" else "medium"))
        opts = dict(getattr(run, "encoder_options", {}) or {})
        opts["encoder"] = encoder
        if encoder == "nvenc":
            opts.setdefault("cq", quality)
            opts.setdefault("preset", preset)
        elif encoder == "qsv":
            opts.setdefault("q", quality)
            opts.setdefault("preset", preset)
        elif encoder == "amf":
            opts.setdefault("qp", quality)
            opts.setdefault("quality", preset)
        elif codec == "av1" and not str(preset).isdigit():
            preset = "6"

        args = _vid_args(codec, quality, preset, opts)

        scale_key = str(run.scale or "").strip().lower()
        scale_key = {"1080": "1080p", "720": "720p"}.get(scale_key, scale_key)
        scale_filter = _scale(scale_key)
        if scale_filter:
            args = ["-vf", scale_filter] + args

        args.extend(parse_extra_args(run.extra_args))
        return args

    def _encode_segment(self, input_path: str, output_path: str, run, segment) -> None:
        cmd = [
            str(self.tools.ffmpeg),
            "-y",
            "-hide_banner",
            "-loglevel", "error",
            "-ss", f"{segment.start_s:.3f}",
            "-t", f"{segment.duration_s:.3f}",
            "-i", input_path,
            "-map", "0:v:0",
            "-an",
            "-sn",
            *self._video_args(run),
            output_path,
        ]
        self._run_process(cmd, label="Encode")

    def _probe_output(self, output_path: str) -> dict:
        cmd = [
            str(self.tools.ffprobe),
            "-v", "error",
            "-show_streams",
            "-show_format",
            "-of", "json",
            output_path,
        ]
        _rc, out, _err = self._run_process(cmd, label="ffprobe")
        try:
            return json.loads(out or "{}")
        except Exception:
            return {}

    def _analyze_result(self, input_path: str, output_path: str, run, segment) -> QualityMetricResult:
        probe = self._probe_output(output_path)
        streams = probe.get("streams") or []
        video = next((s for s in streams if s.get("codec_type") == "video"), {})
        fmt = probe.get("format") or {}
        size = Path(output_path).stat().st_size if Path(output_path).exists() else 0
        duration = float(fmt.get("duration") or video.get("duration") or segment.duration_s or 0.0)
        bitrate_k = float(fmt.get("bit_rate") or 0) / 1000.0 if fmt.get("bit_rate") else 0.0
        result = QualityMetricResult(
            run_name=run.name,
            segment_label=segment.label,
            output_path=output_path,
            size_bytes=size,
            duration_s=duration,
            video_bitrate_kbps=bitrate_k,
            codec=str(video.get("codec_name") or ""),
            pix_fmt=str(video.get("pix_fmt") or ""),
            profile=str(video.get("profile") or ""),
        )
        width = int(video.get("width") or 0)
        height = int(video.get("height") or 0)
        result.ssim = self._measure_ssim(input_path, output_path, segment, width, height, result.notes)
        result.vmaf = self._measure_vmaf(input_path, output_path, segment, width, height, result.notes)
        return result

    def _metric_filter(self, metric: str, width: int, height: int) -> str:
        width = max(16, width or 1920)
        height = max(16, height or 1080)
        return (
            f"[0:v]setpts=PTS-STARTPTS,scale={width}:{height}:flags=bicubic,format=yuv420p[ref];"
            f"[1:v]setpts=PTS-STARTPTS,format=yuv420p[dist];"
            f"[dist][ref]{metric}"
        )

    def _measure_ssim(self, input_path: str, output_path: str, segment, width: int, height: int, notes: list[str]) -> float | None:
        cmd = [
            str(self.tools.ffmpeg),
            "-hide_banner",
            "-nostats",
            "-v", "info",
            "-ss", f"{segment.start_s:.3f}",
            "-t", f"{segment.duration_s:.3f}",
            "-i", input_path,
            "-i", output_path,
            "-filter_complex", self._metric_filter("ssim", width, height),
            "-f", "null",
            "-",
        ]
        try:
            _rc, _out, err = self._run_process(cmd, label="SSIM")
            match = re.search(r"All:([0-9.]+)", err or "")
            return float(match.group(1)) if match else None
        except Exception as exc:
            notes.append(f"SSIM nicht verfügbar: {str(exc)[:160]}")
            return None

    def _measure_vmaf(self, input_path: str, output_path: str, segment, width: int, height: int, notes: list[str]) -> float | None:
        cmd = [
            str(self.tools.ffmpeg),
            "-hide_banner",
            "-nostats",
            "-v", "info",
            "-ss", f"{segment.start_s:.3f}",
            "-t", f"{segment.duration_s:.3f}",
            "-i", input_path,
            "-i", output_path,
            "-filter_complex", self._metric_filter("libvmaf", width, height),
            "-f", "null",
            "-",
        ]
        try:
            _rc, _out, err = self._run_process(cmd, label="VMAF")
            match = re.search(r"VMAF score:\s*([0-9.]+)", err or "")
            return float(match.group(1)) if match else None
        except Exception as exc:
            notes.append(f"VMAF nicht verfügbar: {str(exc)[:160]}")
            return None

    def _log_result(self, result: QualityMetricResult) -> None:
        size_mb = result.size_bytes / 1024 / 1024 if result.size_bytes else 0.0
        ssim = f"{result.ssim:.5f}" if result.ssim is not None else "n/v"
        vmaf = f"{result.vmaf:.2f}" if result.vmaf is not None else "n/v"
        self.log_line.emit(
            f"✅ {result.run_name} / {result.segment_label}: "
            f"{size_mb:.2f} MB | {result.video_bitrate_kbps:.0f} kbps | "
            f"{result.codec} {result.profile} {result.pix_fmt} | SSIM {ssim} | VMAF {vmaf}"
        )
        for note in result.notes:
            self.log_line.emit(f"⚠️  {note}")
