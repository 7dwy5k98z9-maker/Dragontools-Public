# -*- coding: utf-8 -*-
"""Planning/rendering/commit operation for audio/video matching."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from ..core.audio_video_matcher import AudioSyncPlanner
from ..core.timeout_settings import get_timeout
from .audio_video_match_contracts import AudioVideoMatchCallbacks, AudioVideoMatchRequest
from .audio_video_match_render import build_audio_command, build_mux_command, validate_output
from .audio_video_match_reporting import log_plan
from .audio_video_match_runtime import AudioVideoMatchProgress, AudioVideoMatchToolIO
from .tool_runner import log_tool_failure, run_tool


class AudioVideoMatchCreateService:
    def __init__(
        self,
        *,
        tools: Any,
        callbacks: AudioVideoMatchCallbacks,
        progress: AudioVideoMatchProgress,
        tool_io: AudioVideoMatchToolIO,
    ) -> None:
        self._tools = tools
        self._callbacks = callbacks
        self._progress = progress
        self._tool_io = tool_io

    def create(self, request: AudioVideoMatchRequest) -> None:
        from .audio_video_match_analysis_service import AudioVideoMatchAnalysisService

        AudioVideoMatchAnalysisService.require_inputs(request)
        mapping = request.mapping_result
        if mapping is None:
            raise RuntimeError("Bitte zuerst analysieren.")
        if not request.output_path:
            raise RuntimeError("Bitte einen Ausgabepfad wählen.")
        output = Path(request.output_path)
        if output.exists():
            raise RuntimeError(f"Ausgabe existiert bereits und wird nicht überschrieben: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)

        plan = AudioSyncPlanner().build_plan(
            mapping,
            audio_stream_index=request.audio_stream_index,
            cut_results=list(request.cut_results),
        )
        self._callbacks.plan_ready(plan)
        log_plan(plan, self._callbacks.log_line)
        if plan.blocked:
            raise RuntimeError(plan.block_reason or "Audio-Sync-Plan wurde blockiert.")

        temp_dir = Path(tempfile.mkdtemp(prefix="dt_avmatch_"))
        temp_audio = temp_dir / "german_synced.mka"
        temp_output = temp_dir / f"{output.stem}.mkv"
        try:
            self._render_audio(request, plan, temp_audio)
            self._mux_output(request, temp_audio, temp_output)
            self._validate_and_commit(mapping, temp_output, output)
        finally:
            self._cleanup_temp_dir(temp_dir)

    def _render_audio(self, request, plan, temp_audio: Path) -> None:
        self._progress.set(5)
        self._callbacks.log_line("ℹ️  Deutsche Audiospur wird angepasst.")
        result = run_tool(
            build_audio_command(self._tools, request.source_path, plan, temp_audio),
            label="Audio anpassen",
            worker=self._tool_io.process_worker,
            log=self._tool_io.log,
            timeout_s=get_timeout("avmatch_process"),
        )
        if not result.ok:
            log_tool_failure(result, label="Audio anpassen", log=self._tool_io.log, tool_name="ffmpeg")
            raise RuntimeError("Audio-Anpassung fehlgeschlagen.")
        self._progress.set(65)

    def _mux_output(self, request, temp_audio: Path, temp_output: Path) -> None:
        self._callbacks.log_line("ℹ️  Zielvideo und angepasste Audiospur werden gemuxt.")
        result = run_tool(
            build_mux_command(self._tools, request.target_path, temp_audio, temp_output),
            label="MKV muxen",
            worker=self._tool_io.process_worker,
            log=self._tool_io.log,
            timeout_s=get_timeout("avmatch_process"),
        )
        if not result.ok:
            log_tool_failure(result, label="MKV muxen", log=self._tool_io.log, tool_name="ffmpeg")
            raise RuntimeError("Muxing fehlgeschlagen.")
        if not temp_output.is_file() or temp_output.stat().st_size <= 0:
            raise RuntimeError("Ausgabedatei wurde nicht erzeugt.")

    def _validate_and_commit(self, mapping, temp_output: Path, output: Path) -> None:
        duration = validate_output(
            temp_output,
            self._tools,
            target_duration_s=mapping.target_info.duration_s,
        )
        self._callbacks.log_line(f"✅ Ausgabe geprüft: Dauer {duration:.1f}s")
        os.replace(temp_output, output)
        self._progress.set(100)
        self._callbacks.log_line(f"✅ Datei erstellt: {output}")
        self._callbacks.result_ready(str(output))

    def _cleanup_temp_dir(self, temp_dir: Path) -> None:
        try:
            shutil.rmtree(temp_dir)
        except FileNotFoundError:
            return
        except OSError as exc:
            self._callbacks.log_line(
                f"⚠️  Temporärer Matcher-Ordner konnte nicht gelöscht werden: {exc}"
            )


__all__ = ["AudioVideoMatchCreateService"]
