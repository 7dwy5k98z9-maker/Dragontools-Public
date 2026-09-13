from __future__ import annotations

import re


class QualityMetricsService:
    def __init__(self, *, ffmpeg: str, process_runner) -> None:
        self._ffmpeg = str(ffmpeg)
        self._runner = process_runner

    @staticmethod
    def comparison_filter(metric: str, width: int, height: int) -> str:
        width = max(16, int(width or 1920))
        height = max(16, int(height or 1080))
        return (
            f"[0:v]settb=AVTB,setpts=PTS-STARTPTS,scale={width}:{height}:flags=bicubic,format=yuv420p[ref];"
            f"[1:v]settb=AVTB,setpts=PTS-STARTPTS,scale={width}:{height}:flags=bicubic,format=yuv420p[dist];"
            f"[dist][ref]{metric}"
        )

    @staticmethod
    def encoded_filter(metric: str, width: int, height: int) -> str:
        width = max(16, int(width or 1920))
        height = max(16, int(height or 1080))
        return (
            f"[0:v]setpts=PTS-STARTPTS,scale={width}:{height}:flags=bicubic,format=yuv420p[ref];"
            f"[1:v]setpts=PTS-STARTPTS,format=yuv420p[dist];"
            f"[dist][ref]{metric}"
        )

    def measure_comparison(self, *, metric: str, file_a: str, file_b: str, start_a: float, start_b: float,
                           duration: float, width: int, height: int, label: str, notes: list[str]) -> float | None:
        cmd = [
            self._ffmpeg, "-hide_banner", "-nostats", "-v", "info",
            "-ss", f"{start_a:.6f}", "-i", file_a,
            "-ss", f"{start_b:.6f}", "-i", file_b,
            "-t", f"{duration:.6f}",
            "-filter_complex", self.comparison_filter(metric, width, height),
            "-f", "null", "-",
        ]
        return self._measure(cmd, metric=metric, label=label, notes=notes, max_error=180)

    def measure_encoded(self, *, metric: str, input_path: str, output_path: str, start_s: float, duration_s: float,
                        width: int, height: int, label: str, notes: list[str]) -> float | None:
        cmd = [
            self._ffmpeg, "-hide_banner", "-nostats", "-v", "info",
            "-ss", f"{start_s:.3f}", "-t", f"{duration_s:.3f}", "-i", input_path,
            "-i", output_path,
            "-filter_complex", self.encoded_filter(metric, width, height),
            "-f", "null", "-",
        ]
        return self._measure(cmd, metric=metric, label=label, notes=notes, max_error=160)

    def _measure(self, cmd: list[str], *, metric: str, label: str, notes: list[str], max_error: int) -> float | None:
        display = "VMAF" if metric == "libvmaf" else "SSIM"
        try:
            _rc, _out, err = self._runner.run(cmd, label=label)
        except (OSError, RuntimeError, ValueError) as exc:
            notes.append(f"{display} nicht verfügbar: {str(exc)[:max_error]}")
            return None
        pattern = r"VMAF score:\s*([0-9.]+)" if metric == "libvmaf" else r"All:([0-9.]+)"
        match = re.search(pattern, err or "")
        return float(match.group(1)) if match else None
