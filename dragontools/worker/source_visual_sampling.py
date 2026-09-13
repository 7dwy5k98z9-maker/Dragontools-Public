# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from ..core.process_runner import subprocess_no_window_kwargs as no_window_kwargs
from .source_visual_models import SourceVisualCheckSettings


class SourceVisualSampler:
    """FFprobe/FFmpeg I/O for the source visual checker."""

    def __init__(self, *, ffmpeg_path: str, ffprobe_path: str) -> None:
        self.ffmpeg_path = str(ffmpeg_path or "")
        self.ffprobe_path = str(ffprobe_path or "")

    def probe_duration(self, path: Path) -> float:
        try:
            result = subprocess.run(
                [
                    self.ffprobe_path,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "json",
                    str(path),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdin=subprocess.DEVNULL,
                **no_window_kwargs(),
                timeout=20,
            )
            data = json.loads(result.stdout or "{}")
            return float((data.get("format") or {}).get("duration") or 0.0)
        except Exception:
            return 0.0

    @staticmethod
    def video_filter(settings: SourceVisualCheckSettings) -> str:
        width = int(settings.analysis_width)
        height = int(settings.analysis_height)
        return (
            f"fps={max(1, int(settings.fps))},"
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
            "format=rgb24"
        )

    def read_single(
        self,
        path: Path,
        start_s: float,
        settings: SourceVisualCheckSettings,
    ) -> bytes:
        cmd = [
            self.ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{max(0.0, start_s):.3f}",
            "-t",
            str(max(1, int(settings.sample_duration_s))),
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-an",
            "-sn",
            "-vf",
            self.video_filter(settings),
            "-f",
            "rawvideo",
            "-",
        ]
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                **no_window_kwargs(),
                timeout=max(15, int(settings.sample_duration_s) + 15),
            )
            if result.returncode != 0:
                return b""
            return bytes(result.stdout or b"")
        except Exception:
            return b""

    def read_group(
        self,
        path: Path,
        start_points: list[float],
        settings: SourceVisualCheckSettings,
    ) -> list[bytes] | None:
        """Read several independently seeked windows in one FFmpeg process."""
        if not start_points:
            return []
        sample_duration = max(1, int(settings.sample_duration_s))
        vf = self.video_filter(settings)

        try:
            with tempfile.TemporaryDirectory(prefix="dragontools_visual_") as tmp_dir:
                root = Path(tmp_dir)
                outputs = [root / f"probe_{index:02d}.rgb" for index in range(len(start_points))]
                cmd = [self.ffmpeg_path, "-hide_banner", "-loglevel", "error", "-y"]
                for start_s in start_points:
                    cmd.extend(
                        [
                            "-ss",
                            f"{max(0.0, start_s):.3f}",
                            "-t",
                            str(sample_duration),
                            "-i",
                            str(path),
                        ]
                    )
                for input_index, output in enumerate(outputs):
                    cmd.extend(
                        [
                            "-map",
                            f"{input_index}:v:0",
                            "-an",
                            "-sn",
                            "-vf",
                            vf,
                            "-f",
                            "rawvideo",
                            str(output),
                        ]
                    )

                result = subprocess.run(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.DEVNULL,
                    **no_window_kwargs(),
                    timeout=max(30, (sample_duration + 15) * len(start_points)),
                )
                if result.returncode != 0:
                    return None
                return [output.read_bytes() if output.is_file() else b"" for output in outputs]
        except Exception:
            return None


__all__ = ["SourceVisualSampler"]
