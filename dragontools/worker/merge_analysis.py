"""Medienanalyse und ffprobe-Auswertung für den Merge-Worker."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core.media_analyzer import analyze_media
from .utility_media_analysis import analyze_owned_media
from ..core.timeout_settings import get_timeout
from .merge_common import (
    MergeUserAbortError,
    audio_signature,
    audio_probe_signature,
    container_from_format_name,
    container_from_path,
    parse_fps,
    subtitle_signature,
    subtitle_probe_signature,
    video_probe_signature,
)
from .tool_runner import run_tool
from ..core.transaction_identity import path_receipt, receipt_matches


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
                "-show_chapters",
                "-show_data",
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

            source_receipt = path_receipt(path)
            self.file_progress.emit(path, 0, "Analysiere")
            media_info = analyze_owned_media(path, self.tools, worker=self, analyzer=analyze_media)
            if self.abort_requested:
                raise MergeUserAbortError("Abgebrochen")
            probe = self._run_json_ffprobe(path)
            if self.abort_requested:
                raise MergeUserAbortError("Abgebrochen")

            if not receipt_matches(path, source_receipt):
                raise OSError("Merge-Quelle wurde während der Analyse verändert.")
            info = self._normalized_input(path, media_info, probe, source_receipt)
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

    @classmethod
    def _normalized_input(cls, path, media_info, probe, source_receipt):
        primary = media_info.primary_video
        if primary is None:
            raise RuntimeError(f"{Path(path).name}: Kein Primärvideo gefunden.")

        format_data = probe.get("format", {}) or {}
        streams = list(probe.get("streams", []) or [])
        program_videos = [
            stream for stream in streams
            if stream.get("codec_type") == "video"
            and not bool((stream.get("disposition") or {}).get("attached_pic", 0))
        ]
        if not program_videos:
            raise RuntimeError("ffprobe bestätigt keinen verarbeitbaren Videostream.")
        video_stream = program_videos[0]
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
        return {
            "path": path,
            "source_receipt": source_receipt,
            "video_bit_depth": getattr(primary, "bit_depth", None),
            "attachment_count": sum(stream.get("codec_type") == "attachment" or bool((stream.get("disposition") or {}).get("attached_pic", 0)) for stream in streams),
            "data_count": sum(stream.get("codec_type") == "data" for stream in streams),
            "container": effective_container,
            "container_from_suffix": suffix_container,
            "container_from_probe": probed_container,
            "format_name": format_names,
            "video_codec": (primary.codec or "").lower(),
            "width": int(primary.width or 0),
            "height": int(primary.height or 0),
            "fps": fps,
            "duration_s": float(getattr(media_info, "duration_s", 0.0) or 0.0),
            "chapter_count": len(list(probe.get("chapters", []) or [])),
            "dynamic_hdr": cls._source_hdr(media_info),
            # ffprobe signatures deliberately include track-header details
            # that the generic MediaInfo model does not retain (sample rate,
            # default disposition, title, codec profile, SAR/color metadata).
            # A Matroska append may only join segments whose corresponding
            # track headers are semantically compatible.
            "video_structure": video_probe_signature(streams),
            "audio_structure": audio_probe_signature(streams),
            "subtitle_structure": subtitle_probe_signature(streams),
            "analysis_warnings": analysis_warnings,
        }

    @staticmethod
    def _source_hdr(media_info):
        return {
            "hdr_format": str(getattr(media_info.primary_video, "hdr_format", "") or "").lower(),
            "hdr10plus": bool(getattr(media_info, "has_hdrplus", False)),
            "dolby_vision": bool(getattr(media_info, "has_dv", False)),
            "dv_profile": int(getattr(media_info, "dv_profile_major", 0) or 0),
        }
