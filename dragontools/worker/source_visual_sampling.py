# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from .source_visual_models import SourceVisualCheckSettings
from .tool_runner import run_tool, run_tool_bytes


class SourceVisualSampler:
    """FFprobe/FFmpeg I/O for the source visual checker.

    ``worker`` is optional so the same sampler can be used both from the
    converter worker and from the manual GUI check.  When supplied, all
    external processes participate in DragonTools' normal cooperative abort
    lifecycle instead of being opaque ``subprocess.run`` calls that remain
    alive until their timeout expires.
    """

    def __init__(self, *, ffmpeg_path: str, ffprobe_path: str, worker=None, abort_on_request=True) -> None:
        self.ffmpeg_path = str(ffmpeg_path or "")
        self.ffprobe_path = str(ffprobe_path or "")
        self.worker = worker
        self.abort_on_request = bool(abort_on_request)

    @property
    def abort_requested(self) -> bool:
        return bool(self.worker is not None and getattr(self.worker, "abort_requested", False)
                    and (self.abort_on_request or getattr(self.worker, 'abort_type', None) == 'sofort'))

    def probe_duration(self, path: Path) -> float:
        result = run_tool(
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
            label="Quellbildprüfung ffprobe",
            timeout_s=20,
            worker=self.worker,
            abort_on_request=self.abort_on_request,
            activity_file=path,
        )
        if not result.ok:
            return 0.0
        try:
            data = json.loads(result.stdout or "{}")
            return float((data.get("format") or {}).get("duration") or 0.0)
        except (json.JSONDecodeError, TypeError, ValueError):
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
        result = run_tool_bytes(
            cmd,
            label="Quellbildprüfung ffmpeg",
            timeout_s=max(15, int(settings.sample_duration_s) + 15),
            worker=self.worker,
            abort_on_request=self.abort_on_request,
            activity_file=path,
        )
        if not result.ok:
            return b""
        return bytes(result.stdout or b"")

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

                result = run_tool(
                    cmd,
                    label="Quellbildprüfung ffmpeg batch",
                    timeout_s=max(30, (sample_duration + 15) * len(start_points)),
                    worker=self.worker,
                    abort_on_request=self.abort_on_request,
                    activity_file=path,
                    stdout_file=subprocess.DEVNULL,
                )
                if result.aborted:
                    # Cancellation is terminal for this check.  Return a
                    # correctly-sized empty batch so the service does not
                    # interpret it as a batch failure and launch per-probe
                    # fallback FFmpeg processes after the user already aborted.
                    return [b""] * len(outputs)
                if not result.ok:
                    return None
                return [output.read_bytes() if output.is_file() else b"" for output in outputs]
        except (OSError, TypeError, ValueError):
            return None


__all__ = ["SourceVisualSampler"]
