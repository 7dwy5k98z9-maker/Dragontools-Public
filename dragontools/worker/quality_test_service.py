# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from ..core.media_analyzer import analyze_media
from ..core.quality_tester import QualityMetricResult, automatic_quality_segments, parse_extra_args, parse_quality_segments, quality_output_name
from .encoder_args import _scale, _vid_args


class QualityTestService:
    def __init__(self, *, tools, process_runner, metrics, log, progress, result_ready, is_aborted) -> None:
        self._tools = tools
        self._runner = process_runner
        self._metrics = metrics
        self._log = log
        self._progress = progress
        self._result_ready = result_ready
        self._is_aborted = is_aborted

    def run(self, *, files: list[str], output_dir: str, runs: list, sample_count: int, sample_duration_s: int, manual_ranges: str) -> None:
        if not files:
            self._log("⚠️ Keine Dateien im Qualitätstester.")
            return
        if not runs:
            self._log("⚠️ Keine aktiven Testläufe definiert.")
            return
        out_root = Path(output_dir)
        out_root.mkdir(parents=True, exist_ok=True)
        file_segments = self._collect_segments(files, sample_count, sample_duration_s, manual_ranges)
        total_units = sum(len(segments) * len(runs) for _, segments in file_segments)
        done_units = 0
        self._progress(0)
        for file_path, segments in file_segments:
            if self._is_aborted():
                self._log("⚠️ Qualitätstest abgebrochen.")
                return
            file_out_dir = out_root / Path(file_path).stem
            file_out_dir.mkdir(parents=True, exist_ok=True)
            self._log(f"▶ Qualitätstest: {Path(file_path).name}")
            for segment in segments:
                for test_run in runs:
                    if self._is_aborted():
                        self._log("⚠️ Qualitätstest abgebrochen.")
                        return
                    self._run_case(file_path, file_out_dir, test_run, segment)
                    done_units += 1
                    self._progress(int(done_units / max(total_units, 1) * 100))
        self._progress(100)

    def _collect_segments(self, files, sample_count, sample_duration_s, manual_ranges):
        collected = []
        for file_path in files:
            if self._is_aborted():
                break
            media = analyze_media(file_path, self._tools)
            duration = float(getattr(media, "duration_s", 0.0) or 0.0)
            segments = parse_quality_segments(manual_ranges, duration_s=duration, default_duration_s=float(sample_duration_s))
            if not segments:
                segments = automatic_quality_segments(duration_s=duration, count=sample_count, segment_duration_s=float(sample_duration_s))
            collected.append((file_path, segments))
        return collected

    def _run_case(self, file_path: str, output_dir: Path, test_run, segment) -> None:
        output_path = output_dir / quality_output_name(file_path, test_run, segment)
        self._log(f"ℹ️  {test_run.name}: Segment {segment.label} ({segment.duration_s:.0f}s ab {segment.start_s:.1f}s)")
        try:
            self.encode_segment(file_path, str(output_path), test_run, segment)
            result = self.analyze_result(file_path, str(output_path), test_run, segment)
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            self._log(f"❌ Testlauf fehlgeschlagen: {exc}")
            return
        self._result_ready(result)
        self.log_result(result)

    @staticmethod
    def video_args(run) -> list[str]:
        codec = (run.codec or "h265").lower()
        codec = "h265" if codec in {"hevc", "x265"} else "h264" if codec in {"avc", "x264"} else codec
        if codec not in {"h264", "h265", "av1"}:
            codec = "h265"
        encoder = (run.encoder or "cpu").lower()
        aliases = {"software": "cpu", "libx264": "cpu", "libx265": "cpu", "libsvtav1": "cpu", "nvidia": "nvenc", "nvidia nvenc": "nvenc", "intel": "qsv", "intel qsv": "qsv", "amd": "amf", "amd amf": "amf"}
        encoder = aliases.get(encoder, encoder)
        if encoder not in {"cpu", "nvenc", "qsv", "amf"}:
            encoder = "cpu"
        quality = max(0, min(63, int(run.quality)))
        preset = str(run.preset or ("6" if codec == "av1" and encoder == "cpu" else "medium"))
        opts = dict(getattr(run, "encoder_options", {}) or {})
        opts["encoder"] = encoder
        if encoder == "nvenc": opts.setdefault("cq", quality); opts.setdefault("preset", preset)
        elif encoder == "qsv": opts.setdefault("q", quality); opts.setdefault("preset", preset)
        elif encoder == "amf": opts.setdefault("qp", quality); opts.setdefault("quality", preset)
        elif codec == "av1" and not str(preset).isdigit(): preset = "6"
        args = _vid_args(codec, quality, preset, opts)
        scale_key = {"1080": "1080p", "720": "720p"}.get(str(run.scale or "").strip().lower(), str(run.scale or "").strip().lower())
        scale_filter = _scale(scale_key)
        if scale_filter:
            args = ["-vf", scale_filter] + args
        return args + parse_extra_args(run.extra_args)

    def encode_segment(self, input_path: str, output_path: str, run, segment) -> None:
        cmd = [str(self._tools.ffmpeg), "-y", "-hide_banner", "-loglevel", "error",
               "-ss", f"{segment.start_s:.3f}", "-t", f"{segment.duration_s:.3f}", "-i", input_path,
               "-map", "0:v:0", "-an", "-sn", *self.video_args(run), output_path]
        self._runner.run(cmd, label="Encode")

    def probe_output(self, output_path: str) -> dict:
        cmd = [str(self._tools.ffprobe), "-v", "error", "-show_streams", "-show_format", "-of", "json", output_path]
        _rc, out, _err = self._runner.run(cmd, label="ffprobe")
        try:
            value = json.loads(out or "{}")
        except (json.JSONDecodeError, TypeError):
            return {}
        return value if isinstance(value, dict) else {}

    def analyze_result(self, input_path: str, output_path: str, run, segment) -> QualityMetricResult:
        probe = self.probe_output(output_path)
        streams = probe.get("streams") or []
        video = next((s for s in streams if s.get("codec_type") == "video"), {})
        fmt = probe.get("format") or {}
        size = Path(output_path).stat().st_size if Path(output_path).exists() else 0
        duration = float(fmt.get("duration") or video.get("duration") or segment.duration_s or 0.0)
        bitrate_k = float(fmt.get("bit_rate") or 0) / 1000.0 if fmt.get("bit_rate") else 0.0
        result = QualityMetricResult(run_name=run.name, segment_label=segment.label, output_path=output_path, size_bytes=size,
            duration_s=duration, video_bitrate_kbps=bitrate_k, codec=str(video.get("codec_name") or ""),
            pix_fmt=str(video.get("pix_fmt") or ""), profile=str(video.get("profile") or ""))
        width, height = int(video.get("width") or 0), int(video.get("height") or 0)
        result.ssim = self._metrics.measure_encoded(metric="ssim", input_path=input_path, output_path=output_path,
            start_s=segment.start_s, duration_s=segment.duration_s, width=width, height=height, label="SSIM", notes=result.notes)
        result.vmaf = self._metrics.measure_encoded(metric="libvmaf", input_path=input_path, output_path=output_path,
            start_s=segment.start_s, duration_s=segment.duration_s, width=width, height=height, label="VMAF", notes=result.notes)
        return result

    def log_result(self, result: QualityMetricResult) -> None:
        size_mb = result.size_bytes / 1024 / 1024 if result.size_bytes else 0.0
        ssim = f"{result.ssim:.5f}" if result.ssim is not None else "n/v"
        vmaf = f"{result.vmaf:.2f}" if result.vmaf is not None else "n/v"
        self._log(f"✅ {result.run_name} / {result.segment_label}: {size_mb:.2f} MB | {result.video_bitrate_kbps:.0f} kbps | {result.codec} {result.profile} {result.pix_fmt} | SSIM {ssim} | VMAF {vmaf}")
        for note in result.notes:
            self._log(f"⚠️  {note}")
