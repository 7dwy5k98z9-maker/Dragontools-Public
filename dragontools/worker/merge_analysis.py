"""Medienanalyse und ffprobe-Auswertung für den Merge-Worker."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core.media_analyzer import analyze_media
from ..core.timeout_settings import get_timeout
from .merge_common import (
    MergeUserAbortError,
    audio_signature,
    container_from_format_name,
    container_from_path,
    parse_fps,
    subtitle_signature,
)
from .tool_runner import run_tool


class MergeAnalysisMixin:
    """Analysiert Eingaben, ohne Merge-Entscheidungen oder Output-Commit zu treffen."""

    def _run_json_ffprobe(self, path: str) -> dict[str, Any]:
        result = run_tool(
            [
                self.tools.ffprobe,
                "-v",
                "error",
                "-show_format",
                "-show_streams",
                "-of",
                "json",
                path,
            ],
            label="Merge ffprobe",
            timeout_s=get_timeout("media_analysis"),
            worker=self,
            log=self._log,
        )
        if result.aborted or self.abort_requested:
            raise MergeUserAbortError("Abgebrochen")
        if result.timed_out:
            raise RuntimeError("ffprobe: Timeout")
        if not result.ok:
            raise RuntimeError(
                result.stderr.strip()
                or result.stdout.strip()
                or "ffprobe fehlgeschlagen"
            )
        try:
            return json.loads(result.stdout or "{}")
        except Exception as exc:
            raise RuntimeError(f"ffprobe JSON ungültig: {exc}") from exc

    def _analyze_inputs(self, files: list[str]) -> list[dict[str, Any]]:
        infos: list[dict[str, Any]] = []
        total = max(1, len(files))

        for index, path in enumerate(files, start=1):
            if self.abort_requested:
                raise MergeUserAbortError("Abgebrochen")

            self.file_progress.emit(path, 0, "Analysiere")
            media_info = analyze_media(path, self.tools)
            if self.abort_requested:
                raise MergeUserAbortError("Abgebrochen")
            probe = self._run_json_ffprobe(path)
            if self.abort_requested:
                raise MergeUserAbortError("Abgebrochen")

            primary = media_info.primary_video
            if primary is None:
                raise RuntimeError(f"{Path(path).name}: Kein Primärvideo gefunden.")

            format_data = probe.get("format", {}) or {}
            streams = list(probe.get("streams", []) or [])
            video_stream = next(
                (stream for stream in streams if stream.get("codec_type") == "video"),
                {},
            )
            format_names = str(format_data.get("format_name") or "").lower()
            suffix_container = container_from_path(path)
            probed_container = container_from_format_name(format_names)
            effective_container = (
                probed_container if probed_container != "unknown" else suffix_container
            )
            analysis_warnings = list(
                getattr(media_info, "analysis_warnings", []) or []
            )
            if (
                probed_container != "unknown"
                and suffix_container != "unknown"
                and probed_container != suffix_container
            ):
                analysis_warnings.append(
                    "Containerabweichung erkannt: "
                    f"Dateiendung={suffix_container}, ffprobe={probed_container}"
                )
                effective_container = probed_container

            fps = parse_fps(
                str(
                    video_stream.get("avg_frame_rate")
                    or video_stream.get("r_frame_rate")
                    or ""
                )
            )
            info = {
                "path": path,
                "container": effective_container,
                "container_from_suffix": suffix_container,
                "container_from_probe": probed_container,
                "format_name": format_names,
                "video_codec": (primary.codec or "").lower(),
                "width": int(primary.width or 0),
                "height": int(primary.height or 0),
                "fps": fps,
                "audio_structure": audio_signature(list(media_info.audio_streams or [])),
                "subtitle_structure": subtitle_signature(
                    list(media_info.subtitle_streams or [])
                ),
                "analysis_warnings": analysis_warnings,
            }
            infos.append(info)

            self._log(
                f"Analyse {index}/{total}: {Path(path).name} | "
                f"{info['container']} | {info['video_codec']} | "
                f"{info['width']}x{info['height']} | "
                f"FPS={info['fps'] if info['fps'] is not None else 'unbekannt'}"
            )
            for warning in info["analysis_warnings"]:
                self._log(f"Analysewarnung {Path(path).name}: {warning}", "warn")

            progress = min(30, int(index / total * 30))
            self.file_progress.emit(path, progress, info)
            self.progress.emit(progress)

        return infos
