# -*- coding: utf-8 -*-
"""Planning/rendering/commit operation for audio/video matching."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.audio_video_matcher import AudioSyncPlanner
from ..core.timeout_settings import get_timeout
from .audio_video_match_contracts import AudioVideoMatchCallbacks, AudioVideoMatchRequest
from .audio_video_match_render import build_audio_command, build_mux_command, validate_output
from .audio_video_match_reporting import log_plan
from .audio_video_match_runtime import AudioVideoMatchProgress, AudioVideoMatchToolIO
from .tool_runner import log_tool_failure, run_tool
from .utility_output_workspace import VerifiedOutputWorkspace
from ..core.audio_video_match_identity import require_mapping_inputs
from ..core.move_transaction import publish_staged_no_replace


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
        require_mapping_inputs(mapping, request.source_path, request.target_path)
        if not request.output_path:
            raise RuntimeError("Bitte einen Ausgabepfad wählen.")
        output = Path(request.output_path)
        if output.exists() or output.is_symlink():
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

        workspace = VerifiedOutputWorkspace(output.parent, self._tool_io.log, prefix='.__dragontools_avmatch_')
        with workspace as temp_dir:
            temp_audio = temp_dir / "german_synced.mka"
            temp_output = temp_dir / f"{output.stem}.mkv"
            self._render_audio(request, plan, temp_audio)
            self._mux_output(request, plan, temp_audio, temp_output)
            require_mapping_inputs(mapping, request.source_path, request.target_path)
            channels = next(s.channels for s in mapping.source_info.audio_streams if s.index == plan.audio_stream_index)
            self._validate_and_commit(mapping, temp_output, output, plan=plan,
                target_path=request.target_path, audio_channels=channels, workspace=workspace)

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

    def _mux_output(self, request, plan, temp_audio: Path, temp_output: Path) -> None:
        self._callbacks.log_line("ℹ️  Zielvideo und angepasste Audiospur werden gemuxt.")
        result = run_tool(
            build_mux_command(
                self._tools,
                request.target_path,
                temp_audio,
                temp_output,
                plan=plan,
            ),
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

    def _validate_and_commit(self, mapping, temp_output: Path, output: Path, *, plan=None,
                             target_path=None, audio_channels=None, workspace=None) -> None:
        self._tool_io.raise_if_aborted()
        duration = validate_output(
            temp_output,
            self._tools,
            target_duration_s=mapping.target_info.duration_s,
            process_worker=self._tool_io.process_worker, plan=plan,
            target_path=target_path, audio_channels=audio_channels,
        )
        # Validation can be slow enough for a cancellation to arrive after the
        # external mux process has already finished.  Never commit a staged
        # result after an immediate abort request.
        self._tool_io.raise_if_aborted()
        if target_path:
            require_mapping_inputs(mapping, mapping.source_info.path, target_path)
        self._callbacks.log_line(f"✅ Ausgabe geprüft: Dauer {duration:.1f}s")
        if workspace is not None:
            workspace.mark_verified(temp_output)
            workspace.publish_verified(temp_output, output, require_current=self._tool_io.raise_if_aborted)
        else:
            self._tool_io.raise_if_aborted()
            publish_staged_no_replace(temp_output, output)
        self._progress.set(100)
        self._callbacks.log_line(f"✅ Datei erstellt: {output}")
        self._callbacks.result_ready(str(output))

__all__ = ["AudioVideoMatchCreateService"]
