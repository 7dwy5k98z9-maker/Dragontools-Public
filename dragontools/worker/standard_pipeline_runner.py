# -*- coding: utf-8 -*-
from __future__ import annotations

import subprocess
from pathlib import Path

from ..core.codec_utils import normalize_target_codec
from ..core.path_syntax import user_path_name

from .encoder_args import _vid_args
from .hdr10_color import hdr10_output_args
from .workflow_models import PipelineExecutionRequest, PipelineExecutionResult
from .subtitle_sidecar_service import SubtitleSidecarService
from ..rules.subtitle_rules import any_sidecar_export_enabled

_VIDEO_STAT_TAGS_TO_CLEAR = ("BPS", "DURATION", "NUMBER_OF_FRAMES", "NUMBER_OF_BYTES")


def _clear_reencoded_video_stat_tags() -> list[str]:
    args: list[str] = []
    for tag in _VIDEO_STAT_TAGS_TO_CLEAR:
        args += ["-metadata:s:v:0", f"{tag}="]
    return args


class StandardPipelineRunner:
    """Führt die Standard-Pipeline inklusive Strip-only und FFmpeg-Encode aus."""

    def __init__(
        self,
        *,
        tools,
        codec: str,
        crf,
        preset: str,
        encoder_options: dict,
        progress_runner,
        log=None,
        subtitle_rules: dict | None = None,
        worker=None,
    ) -> None:
        self._tools = tools
        self._codec = codec
        self._crf = crf
        self._preset = preset
        self._encoder_options = encoder_options
        self._progress_runner = progress_runner
        self._log = log
        self._worker = worker
        self._subtitle_rules = dict(subtitle_rules or {})
        self._subtitle_service = SubtitleSidecarService(
            ffmpeg_path=self._tools.ffmpeg,
            subtitle_rules=self._subtitle_rules,
            log=self._log or (lambda *_args, **_kwargs: None),
            worker=worker,
        )

    def logger_start_params(
        self,
        *,
        encoder_options: dict | None = None,
        crf=None,
        preset: str | None = None,
    ) -> tuple[str, object, str, object]:
        options = encoder_options or self._encoder_options
        active_crf = self._crf if crf is None else crf
        active_preset = preset or self._preset
        enc_key = options.get("encoder", "cpu")
        if enc_key == "nvenc":
            q_val = options.get("cq", active_crf)
            q_label = "CQ"
            preset = options.get("preset", "p6")
        elif enc_key == "qsv":
            q_val = options.get("q", active_crf)
            q_label = "q"
            preset = options.get("preset", "medium")
        elif enc_key == "amf":
            q_val = options.get("qp", active_crf)
            q_label = "QP"
            preset = options.get("quality", "balanced")
        else:
            q_val = options.get("crf", active_crf)
            q_label = "CRF"
            preset = options.get("preset", active_preset)
        return enc_key, q_val, q_label, preset

    def execute(self, request: PipelineExecutionRequest) -> PipelineExecutionResult:
        """Fuehrt die Standardpipeline ueber den gemeinsamen Pipelinevertrag aus."""
        plan = request.plan
        if plan is None:
            return PipelineExecutionResult(
                success=False,
                failure_stage="Standard-Encoding",
                failure_reason="Encode-Plan fehlt.",
            )

        video_map_count = self._count_video_output_maps(plan.vf_args)
        if video_map_count != 1:
            reason = (
                "Standard-Encoding abgebrochen: unerwartetes Video-Mapping "
                f"({video_map_count} Video-Outputs)."
            )
            if self._log:
                self._log(reason, "error")
            return PipelineExecutionResult(
                success=False,
                failure_stage="Standard-Encoding",
                failure_reason=reason,
            )

        codec = normalize_target_codec(request.codec or self._codec)
        crf = request.crf
        preset = request.preset or self._preset
        encoder_options = dict(request.encoder_options or self._encoder_options)
        output_args = ["-map_metadata", "0"] + _clear_reencoded_video_stat_tags()
        hdr10_args = hdr10_output_args(request.media_info, codec)
        if hdr10_args:
            output_args += hdr10_args
            if codec == "h265":
                encoder_options["_force_hdr10_vui"] = True
            elif codec == "av1":
                encoder_options["_force_10bit"] = True
            if self._log:
                self._log(
                    "Standard-Encoding: HDR10-Ausgabeparameter gesetzt "
                    "(BT.2020/PQ/10-bit/Limited).",
                    "info",
                )
        if str(request.container).lower() in {"mp4", "m4v", "mov"}:
            output_args += ["-movflags", "+faststart"]

        audio_input_args = list(getattr(plan, "audio_input_args", []) or [])
        cmd = (
            [self._tools.ffmpeg, "-y", "-loglevel", "error"]
            + audio_input_args
            + ["-i", request.input_path]
            + plan.vf_args
            + _vid_args(codec, crf, preset, encoder_options)
            + plan.audio_args
            + plan.sn
            + output_args
            + [request.output_path]
        )
        return_code = self._progress_runner(cmd, request.input_path, request.duration_ms)
        if return_code != 0:
            output = str(getattr(self._worker, "_last_stderr", "") or "").strip()
            return PipelineExecutionResult(
                success=False,
                failure_stage="Standard-Encoding",
                failure_reason=f"ffmpeg wurde mit Returncode {return_code} beendet.",
                tool=user_path_name(self._tools.ffmpeg),
                command=subprocess.list2cmdline([str(part) for part in cmd]),
                tool_output=output,
            )

        sidecars: tuple[str, ...] = ()
        target_container = str(request.container).lower()
        if any_sidecar_export_enabled(self._subtitle_rules, container=target_container):
            export = self._subtitle_service.export_sidecars_result(
                input_path=request.input_path,
                output_base=Path(request.output_path).with_suffix(""),
                media_info=request.media_info,
                file_override=request.override,
                container=target_container,
            )
            sidecars = tuple(export.exported_paths)
            if not export.complete:
                return PipelineExecutionResult(
                    success=False,
                    sidecar_paths=sidecars,
                    failure_stage="Untertitel-Export",
                    failure_reason=export.failure_summary() or "Sidecar-Export unvollständig.",
                )
        return PipelineExecutionResult.succeeded(sidecar_paths=sidecars)

    @staticmethod
    def _count_video_output_maps(args: list[str]) -> int:
        count = 0
        for idx, arg in enumerate(args[:-1]):
            if arg != "-map":
                continue
            target = str(args[idx + 1])
            if target.startswith("0:v") or target == "[vout]":
                count += 1
        return count
