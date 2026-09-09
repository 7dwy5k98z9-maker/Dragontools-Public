# -*- coding: utf-8 -*-
from __future__ import annotations

import traceback
from pathlib import Path
from typing import Callable

from .dv_runtime_models import DVTempState
from .dv_subtitle_mux_service import DVSubtitleMuxService
from .hdr10plus_bitstream_service import HDR10PlusBitstreamService
from .hdrplus_encode_service import HDRPlusEncodeService
from .hdrplus_mux_service import HDRPlusMuxService
from .hdrplus_pipeline_coordinator import HDRPlusPipelineCoordinator, HDRPlusPipelineHooks
from .hdrplus_runtime_models import HDRPlusEncoderConfig, HDRPlusExecutionContext
from .hdrplus_stream_service import HDRPlusStreamService
from .hdrplus_tool_runner import HDRPlusToolRunner
from .subtitle_sidecar_service import SubtitleSidecarService
from .tool_runner import log_tool_failure, run_tool
from .workflow_models import PipelineExecutionRequest, PipelineExecutionResult


class HDRPlusConversionHelper:
    """Stabile Fassade fuer den HDR10+-Spezialpfad.

    Der Helper haelt langlebige Tool-/Service-Abhaengigkeiten und schmale
    Kompatibilitaetswrapper. Jobbezogene Encoderwerte und Pipelinezustand werden
    dagegen pro Aufruf als Context an ``HDRPlusPipelineCoordinator`` uebergeben.
    Dadurch kann ein Auftrag keinen Runtime-State des naechsten Auftrags
    ueberschreiben.
    """

    def __init__(
        self,
        *,
        tools,
        log: Callable[[str, str], None],
        codec: str,
        crf: int | str,
        preset: str,
        encoder_options: dict,
        progress_runner,
        temp_state: DVTempState,
        subtitle_rules: dict | None = None,
    ) -> None:
        self._tools = tools
        self._log_fn = log
        # Basiskonfiguration bleibt fuer direkte run()-Kompatibilitaet erhalten,
        # wird von execute() aber nicht mehr jobweise mutiert.
        self._codec = HDRPlusEncoderConfig.create(
            codec=codec,
            crf=crf,
            preset=preset,
            encoder_options=encoder_options,
        ).codec
        self._crf = crf
        self._preset = preset
        self._encoder_options = dict(encoder_options or {})
        self._progress = progress_runner
        self._temp_state = temp_state
        self._worker = getattr(progress_runner, "worker", None)
        self.last_final_hdr10plus_verified = False
        self.last_sidecar_paths: list[str] = []
        self._subtitle_rules = dict(subtitle_rules or {})

        self._subtitle_service = SubtitleSidecarService(
            ffmpeg_path=tools.ffmpeg,
            subtitle_rules=self._subtitle_rules,
            log=self._log,
            worker=self._worker,
        )
        self._subtitle_mux_service = DVSubtitleMuxService(
            ffmpeg_path=tools.ffmpeg,
            subtitle_rules=self._subtitle_rules,
            log=self._log,
        )
        self._hdr10plus_service = HDR10PlusBitstreamService(
            hdr10plus_tool_path=tools.hdr10plus_tool,
            log=self._log,
        )
        self._tool_runner = HDRPlusToolRunner(
            run_tool_fn=lambda *args, **kwargs: run_tool(*args, **kwargs),
            log_tool_failure_fn=lambda *args, **kwargs: log_tool_failure(*args, **kwargs),
            log=self._log,
            temp_state=self._temp_state,
            worker=self._worker,
        )
        self._mux_service = HDRPlusMuxService(
            tools=tools,
            log=self._log,
            run_mux_tool=lambda *args, **kwargs: self._run_mux_tool(*args, **kwargs),
            capture_tool=self._tool_runner.capture,
        )
        self._encode_service = HDRPlusEncodeService(
            ffmpeg_path=tools.ffmpeg,
            progress_runner=self._progress,
            temp_state=self._temp_state,
            log=self._log,
        )
        self._stream_service = HDRPlusStreamService(ffmpeg_path=tools.ffmpeg, log=self._log)
        self._pipeline = HDRPlusPipelineCoordinator(
            encode_service=self._encode_service,
            subtitle_service=self._subtitle_service,
            subtitle_mux_service=self._subtitle_mux_service,
            subtitle_rules=self._subtitle_rules,
            log=self._log,
        )

    def _log(self, msg: str, level: str = "info") -> None:
        self._log_fn(msg, level)

    def _default_encoder_config(self) -> HDRPlusEncoderConfig:
        return HDRPlusEncoderConfig.create(
            codec=self._codec,
            crf=self._crf,
            preset=self._preset,
            encoder_options=self._encoder_options,
        )

    # ------------------------------------------------------------------
    # Schmale Kompatibilitaetswrapper fuer bestehende Tests/Aufrufer
    # ------------------------------------------------------------------

    def _run_hdrplus_tool(
        self,
        cmd: list,
        *,
        label: str,
        tool_name: str,
        accepted_returncodes: tuple[int, ...] = (0,),
    ) -> bool:
        return self._tool_runner.run_hdrplus(
            cmd,
            label=label,
            tool_name=tool_name,
            accepted_returncodes=accepted_returncodes,
        )

    def _run_hdrplus_tool_rc(self, cmd: list, *, allow_error: bool = False) -> int:
        return self._tool_runner.run_hdrplus_rc(cmd, allow_error=allow_error)

    def _verify_final_hdr10plus(self, output_path: str, expected_json: Path) -> bool:
        return self._stream_service.verify_final_hdr10plus(
            output_path,
            expected_json,
            run_tool=self._run_hdrplus_tool,
            run_tool_rc=self._run_hdrplus_tool_rc,
            bitstream_service=self._hdr10plus_service,
        )

    def _extract_hevc_annexb(self, input_path: str, output_hevc: str) -> bool:
        return self._stream_service.extract_hevc_annexb(
            input_path,
            output_hevc,
            run_tool=self._run_hdrplus_tool,
        )

    def _extract_hdr10plus_metadata(self, source_stream: str, meta_json: str) -> bool:
        return self._hdr10plus_service.extract_metadata(
            self._run_hdrplus_tool_rc,
            source_stream=Path(source_stream),
            output_json=Path(meta_json),
        )

    def _inject_hdr10plus_metadata(self, encoded_hevc: str, meta_json: str, injected_hevc: str) -> bool:
        return self._hdr10plus_service.inject_metadata(
            self._run_hdrplus_tool_rc,
            input_hevc=Path(encoded_hevc),
            metadata_json=Path(meta_json),
            output_hevc=Path(injected_hevc),
        )

    @staticmethod
    def _has_aux_stream_output(audio_args: list, subtitle_args: list) -> bool:
        return HDRPlusEncodeService.has_aux_stream_output(audio_args, subtitle_args)

    def _encode_hevc_and_stream_donor(
        self,
        *,
        input_path: str,
        encoded_hevc: Path,
        stream_donor: Path,
        vf_args: list,
        audio_args: list,
        audio_input_args: list,
        subtitle_args: list,
        media_info,
    ) -> bool:
        return self._encode_service.encode(
            input_path=input_path,
            encoded_hevc=encoded_hevc,
            stream_donor=stream_donor,
            vf_args=vf_args,
            audio_args=audio_args,
            audio_input_args=audio_input_args,
            subtitle_args=subtitle_args,
            media_info=media_info,
            encoder=self._default_encoder_config(),
        )

    def _run_mux_tool(
        self,
        cmd: list,
        *,
        label: str,
        tool_name: str,
        accepted_returncodes: tuple[int, ...] = (0,),
    ) -> bool:
        return self._tool_runner.run_mux(
            cmd,
            label=label,
            tool_name=tool_name,
            accepted_returncodes=accepted_returncodes,
        )

    def _mux_hdrplus_mkv(self, injected_hevc: str, stream_donor: str, output_path: str) -> bool:
        return self._mux_service.mux_mkv(injected_hevc, stream_donor, output_path)

    def _probe_mp4_audio(self, donor: Path) -> list[dict] | None:
        return self._mux_service.probe_mp4_audio(donor)

    @staticmethod
    def _audio_ext(codec: str) -> str:
        return HDRPlusMuxService.audio_ext(codec)

    def _mux_hdrplus_mp4(
        self,
        injected_hevc: str,
        stream_donor: str,
        output_path: str,
        *,
        tmp_dir: Path,
        subtitle_tracks=(),
    ) -> bool:
        return self._mux_service.mux_mp4(
            injected_hevc,
            stream_donor,
            output_path,
            tmp_dir=tmp_dir,
            subtitle_tracks=subtitle_tracks,
        )

    def _mux_hdrplus_output(
        self,
        injected_hevc: str,
        stream_donor: str,
        output_path: str,
        *,
        container: str,
        tmp_dir: Path | None = None,
        subtitle_tracks=(),
    ) -> bool:
        target = str(container or "mkv").lower()
        if target == "mkv":
            return self._mux_hdrplus_mkv(injected_hevc, stream_donor, output_path)
        if target == "mp4":
            return self._mux_hdrplus_mp4(
                injected_hevc,
                stream_donor,
                output_path,
                tmp_dir=tmp_dir or Path(output_path).parent,
                subtitle_tracks=subtitle_tracks,
            )
        self._log(f"❌ HDR10+: Nicht unterstützter Zielcontainer: {target}", "error")
        return False

    def _cleanup_tmp_sub(self, input_path: str) -> None:
        tmp_sub = self._temp_state.burn_sub_tmp
        if not tmp_sub:
            return
        try:
            Path(tmp_sub).unlink(missing_ok=True)
        except Exception as exc:
            self._log(
                f"⚠️ Temporäre Datei konnte nicht gelöscht werden: {Path(tmp_sub).name} – {exc}",
                "warn",
            )
            self._log(traceback.format_exc(), "error")
        finally:
            self._temp_state.burn_sub_tmp = None

    # ------------------------------------------------------------------
    # Oeffentliche Pipeline-Schnittstellen
    # ------------------------------------------------------------------

    def execute(self, request: PipelineExecutionRequest) -> PipelineExecutionResult:
        plan = request.plan
        if plan is None:
            return PipelineExecutionResult(
                success=False,
                failure_stage="HDR10+-Preflight",
                failure_reason="Encode-Plan fehlt.",
            )

        encoder = HDRPlusEncoderConfig.create(
            codec=request.codec,
            crf=request.crf,
            preset=request.preset,
            encoder_options=request.encoder_options,
        )
        outcome = self._run_pipeline(
            input_path=request.input_path,
            output_path=request.output_path,
            media_info=request.media_info,
            vf_args=plan.vf_args,
            audio_args=plan.audio_args,
            audio_input_args=list(getattr(plan, "audio_input_args", []) or []),
            subtitle_args=plan.sn,
            crop=plan.crop,
            container=request.container,
            override=request.override,
            encoder=encoder,
        )
        failure_reason = self._temp_state.failure_reason
        failure_stage = self._temp_state.failure_stage
        if not outcome.success and not failure_reason:
            failure_reason = "HDR10+-Pipeline fehlgeschlagen."
            failure_stage = failure_stage or "HDR10+"
        return PipelineExecutionResult(
            success=outcome.success,
            sidecar_paths=outcome.sidecar_paths,
            verified_hdr10plus=bool(outcome.success and outcome.verified_hdr10plus),
            failure_reason=failure_reason,
            failure_stage=failure_stage,
            tool_output=self._temp_state.stderr,
            tool=self._temp_state.last_tool,
            command=self._temp_state.last_command,
        )

    def run(
        self,
        input_path: str,
        output_path: str,
        mi,
        vf_args: list,
        audio_args: list,
        audio_input_args: list | None,
        sn: list,
        crop: str | None,
        container: str = "mkv",
        override: dict | None = None,
    ) -> bool:
        outcome = self._run_pipeline(
            input_path=input_path,
            output_path=output_path,
            media_info=mi,
            vf_args=vf_args,
            audio_args=audio_args,
            audio_input_args=audio_input_args,
            subtitle_args=sn,
            crop=crop,
            container=container,
            override=override,
            encoder=self._default_encoder_config(),
        )
        return outcome.success

    def _run_pipeline(
        self,
        *,
        input_path: str,
        output_path: str,
        media_info,
        vf_args,
        audio_args,
        audio_input_args,
        subtitle_args,
        crop: str | None,
        container: str,
        override,
        encoder: HDRPlusEncoderConfig,
    ):
        self.last_final_hdr10plus_verified = False
        self.last_sidecar_paths = []
        self._temp_state.reset_diagnostics()
        context = HDRPlusExecutionContext.create(
            input_path=input_path,
            output_path=output_path,
            media_info=media_info,
            vf_args=vf_args,
            audio_args=audio_args,
            audio_input_args=audio_input_args,
            subtitle_args=subtitle_args,
            crop=crop,
            container=container,
            override=override,
            encoder=encoder,
        )
        hooks = HDRPlusPipelineHooks(
            extract_hevc_annexb=self._extract_hevc_annexb,
            extract_metadata=self._extract_hdr10plus_metadata,
            inject_metadata=self._inject_hdr10plus_metadata,
            mux_output=self._mux_hdrplus_output,
            run_mux_tool=self._run_mux_tool,
            verify_final=self._verify_final_hdr10plus,
            cleanup_tmp_sub=self._cleanup_tmp_sub,
        )
        outcome = self._pipeline.run(context, hooks)
        self.last_final_hdr10plus_verified = bool(outcome.verified_hdr10plus)
        self.last_sidecar_paths = list(outcome.sidecar_paths)
        return outcome
