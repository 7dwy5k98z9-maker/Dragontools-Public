# -*- coding: utf-8 -*-
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from ..core.codec_utils import normalize_target_codec
from ..core.path_syntax import user_path_name

from .encoder_args import _vid_args
from .comfyui_video_worker import ComfyUIHDRVideoService
from .hdr10_color import hdr10_output_args
from .workflow_models import PipelineExecutionRequest, PipelineExecutionResult
from .subtitle_sidecar_service import SubtitleSidecarService
from .converter_subtitle_args import build_subtitle_args
from ..rules.subtitle_rules import any_sidecar_export_enabled, compute_subtitle_plan

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
        enhancement_hdr = bool(encoder_options.get("_sdr_hdr_applied", False))
        hdr10_args = hdr10_output_args(request.media_info, codec, force_hdr=enhancement_hdr)
        if hdr10_args:
            output_args += hdr10_args
            if codec == "h265":
                encoder_options["_force_hdr10_vui"] = True
            elif codec == "av1":
                encoder_options["_force_10bit"] = True
            if self._log:
                prefix = "SDR→HDR Enhancement" if enhancement_hdr else "Standard-Encoding"
                self._log(
                    f"{prefix}: HDR10-Ausgabeparameter gesetzt "
                    "(BT.2020/PQ/10-bit/Limited).",
                    "info",
                )
        if str(request.container).lower() in {"mp4", "m4v", "mov"}:
            output_args += ["-movflags", "+faststart"]

        if enhancement_hdr and str(encoder_options.get("sdr_hdr_backend", "ffmpeg") or "ffmpeg").strip().lower() == "comfyui":
            return self._execute_comfyui_hdr(
                request=request,
                codec=codec,
                crf=crf,
                preset=preset,
                encoder_options=encoder_options,
                hdr10_args=hdr10_args,
                output_args=output_args,
            )

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
            fallback = self._try_mov_text_fallback(
                request=request,
                original_command=cmd,
                output_args=output_args,
                codec=codec,
                crf=crf,
                preset=preset,
                encoder_options=encoder_options,
            )
            if fallback is not None:
                return fallback
            output = str(getattr(self._worker, "_last_stderr", "") or "").strip()
            return PipelineExecutionResult(
                success=False,
                failure_stage="Standard-Encoding",
                failure_reason=f"ffmpeg wurde mit Returncode {return_code} beendet.",
                tool=user_path_name(self._tools.ffmpeg),
                command=subprocess.list2cmdline([str(part) for part in cmd]),
                tool_output=output,
            )

        return self._finish_sidecars(request)

    def _execute_comfyui_hdr(
        self,
        *,
        request: PipelineExecutionRequest,
        codec: str,
        crf,
        preset: str,
        encoder_options: dict,
        hdr10_args: list[str],
        output_args: list[str],
    ) -> PipelineExecutionResult:
        plan = request.plan
        if plan is None:
            return PipelineExecutionResult(False, failure_stage="ComfyUI/HDRTVDM", failure_reason="Encode-Plan fehlt.")

        parent = Path(request.output_path).parent
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="dragontools_comfyui_", dir=parent) as temp_dir:
            temp_root = Path(temp_dir)
            hdr_video = temp_root / "hdrtvdm_video.mkv"
            manifest = temp_root / "hdrtvdm_manifest.json"
            video_args = _vid_args(codec, crf, preset, encoder_options)
            service = ComfyUIHDRVideoService(tools=self._tools, worker=self._worker, log=self._log)
            rendered = service.render(
                input_path=request.input_path,
                output_path=str(hdr_video),
                media_info=request.media_info,
                encoder_options=encoder_options,
                decode_args=list(plan.vf_args),
                encode_args=video_args,
                hdr_output_args=hdr10_args,
                manifest_path=str(manifest),
            )
            if not rendered.success:
                return PipelineExecutionResult(
                    False,
                    failure_stage="ComfyUI/HDRTVDM",
                    failure_reason=rendered.message or rendered.error or "AI-HDR-Konvertierung fehlgeschlagen.",
                    tool="ComfyUI",
                    tool_output=rendered.error,
                )
            if self._log:
                vram = f", Peak-VRAM {rendered.peak_vram_bytes / 1024**3:.2f} GiB" if rendered.peak_vram_bytes else ""
                elapsed = f", {rendered.elapsed_s:.1f}s" if rendered.elapsed_s > 0 else ""
                self._log(f"✅ ComfyUI/HDRTVDM: {rendered.frames} Frames verarbeitet{elapsed}{vram}.", "info")

            mux_cmd = (
                [self._tools.ffmpeg, "-y", "-loglevel", "error"]
                + list(getattr(plan, "audio_input_args", []) or [])
                + ["-i", request.input_path, "-i", str(hdr_video), "-map", "1:v:0", "-c:v", "copy"]
                + list(plan.audio_args)
                + list(plan.sn)
                + output_args
                + [request.output_path]
            )
            return_code = self._progress_runner(mux_cmd, request.input_path, request.duration_ms)
            fallback_sidecars: tuple[str, ...] = ()
            if return_code != 0:
                mov_streams = self._selected_mkv_mov_text_streams(request)
                if mov_streams:
                    backup = self._export_mov_text_backup(request, mov_streams)
                    if not backup.complete:
                        return PipelineExecutionResult(
                            False,
                            sidecar_paths=tuple(backup.exported_paths),
                            failure_stage="mov_text-Fallback",
                            failure_reason=backup.failure_summary() or "mov_text-Fallback konnte nicht gesichert werden.",
                        )
                    fallback_sidecars = tuple(backup.exported_paths)
                    _burn, fallback_sn = build_subtitle_args(
                        self._worker, request.input_path, request.media_info, request.override,
                        container=request.container, subtitle_rules=self._subtitle_rules,
                        exclude_mkv_stream_indices={int(stream.index) for stream in mov_streams},
                    )
                    retry_cmd = (
                        [self._tools.ffmpeg, "-y", "-loglevel", "error"]
                        + list(getattr(plan, "audio_input_args", []) or [])
                        + ["-i", request.input_path, "-i", str(hdr_video), "-map", "1:v:0", "-c:v", "copy"]
                        + list(plan.audio_args)
                        + list(fallback_sn)
                        + output_args
                        + [request.output_path]
                    )
                    if self._log:
                        self._log("⚠️ mov_text→SRT fehlgeschlagen; Originalspur als MP4-Sidecar gesichert. Mux wird ohne diese Spur wiederholt.", "warn")
                    return_code = self._progress_runner(retry_cmd, request.input_path, request.duration_ms)
                    if return_code == 0:
                        return self._finish_sidecars(
                            request,
                            initial_sidecars=fallback_sidecars,
                            externalized_subtitle_stream_indices=tuple(int(stream.index) for stream in mov_streams),
                        )
                    self._cleanup_sidecars(fallback_sidecars)
                    mux_cmd = retry_cmd
                output = str(getattr(self._worker, "_last_stderr", "") or "").strip()
                return PipelineExecutionResult(
                    False, failure_stage="ComfyUI-HDR-Mux",
                    failure_reason=f"ffmpeg wurde mit Returncode {return_code} beendet.",
                    tool=user_path_name(self._tools.ffmpeg),
                    command=subprocess.list2cmdline([str(part) for part in mux_cmd]),
                    tool_output=output,
                )
        return self._finish_sidecars(request)

    def _selected_mkv_mov_text_streams(self, request: PipelineExecutionRequest):
        if str(request.container or "mkv").lower() in {"mp4", "m4v", "mov"}:
            return []
        plan = compute_subtitle_plan(
            list(getattr(request.media_info, "subtitle_streams", None) or []),
            audio_streams=list(getattr(request.media_info, "audio_streams", None) or []),
            file_override=request.override,
            subtitle_rules=self._subtitle_rules,
            container_copy_supported=True,
            media_duration_s=getattr(request.media_info, "duration_s", None),
        )
        return [
            stream for stream in list(getattr(plan, "keep_streams", ()) or ())
            if str(getattr(stream, "codec", "") or "").strip().lower() in {"mov_text", "tx3g"}
        ]

    def _export_mov_text_backup(self, request: PipelineExecutionRequest, streams):
        return self._subtitle_service.export_mov_text_backup_result(
            input_path=request.input_path,
            output_base=Path(request.output_path).with_suffix(""),
            streams=streams,
        )

    def _try_mov_text_fallback(
        self,
        *,
        request: PipelineExecutionRequest,
        original_command: list[str],
        output_args: list[str],
        codec: str,
        crf,
        preset: str,
        encoder_options: dict,
    ) -> PipelineExecutionResult | None:
        mov_streams = self._selected_mkv_mov_text_streams(request)
        if not mov_streams:
            return None
        backup = self._export_mov_text_backup(request, mov_streams)
        if not backup.complete:
            return PipelineExecutionResult(
                False,
                sidecar_paths=tuple(backup.exported_paths),
                failure_stage="mov_text-Fallback",
                failure_reason=backup.failure_summary() or "mov_text-Fallback konnte nicht gesichert werden.",
            )
        _burn, fallback_sn = build_subtitle_args(
            self._worker, request.input_path, request.media_info, request.override,
            container=request.container, subtitle_rules=self._subtitle_rules,
            exclude_mkv_stream_indices={int(stream.index) for stream in mov_streams},
        )
        plan = request.plan
        retry_cmd = (
            [self._tools.ffmpeg, "-y", "-loglevel", "error"]
            + list(getattr(plan, "audio_input_args", []) or [])
            + ["-i", request.input_path]
            + list(plan.vf_args)
            + _vid_args(codec, crf, preset, encoder_options)
            + list(plan.audio_args)
            + list(fallback_sn)
            + output_args
            + [request.output_path]
        )
        if self._log:
            self._log(
                "⚠️ mov_text→SRT konnte nicht erfolgreich abgeschlossen werden; "
                "Originalspur wurde verlustfrei als Subtitle-only-MP4 gesichert. Encoding wird ohne diese interne Spur wiederholt.",
                "warn",
            )
        retry_code = self._progress_runner(retry_cmd, request.input_path, request.duration_ms)
        if retry_code == 0:
            return self._finish_sidecars(
                request,
                initial_sidecars=tuple(backup.exported_paths),
                externalized_subtitle_stream_indices=tuple(int(stream.index) for stream in mov_streams),
            )
        self._cleanup_sidecars(tuple(backup.exported_paths))
        output = str(getattr(self._worker, "_last_stderr", "") or "").strip()
        return PipelineExecutionResult(
            False,
            failure_stage="Standard-Encoding",
            failure_reason=f"ffmpeg wurde auch ohne mov_text mit Returncode {retry_code} beendet.",
            tool=user_path_name(self._tools.ffmpeg),
            command=subprocess.list2cmdline([str(part) for part in retry_cmd]),
            tool_output=output,
        )

    @staticmethod
    def _cleanup_sidecars(paths: tuple[str, ...]) -> None:
        for item in paths:
            try:
                Path(item).unlink(missing_ok=True)
            except OSError:
                pass

    def _finish_sidecars(
        self,
        request: PipelineExecutionRequest,
        *,
        initial_sidecars: tuple[str, ...] = (),
        externalized_subtitle_stream_indices: tuple[int, ...] = (),
    ) -> PipelineExecutionResult:
        sidecars: tuple[str, ...] = tuple(initial_sidecars)
        target_container = str(request.container).lower()
        if any_sidecar_export_enabled(self._subtitle_rules, container=target_container):
            export = self._subtitle_service.export_sidecars_result(
                input_path=request.input_path,
                output_base=Path(request.output_path).with_suffix(""),
                media_info=request.media_info,
                file_override=request.override,
                container=target_container,
            )
            sidecars = tuple(dict.fromkeys((*sidecars, *tuple(export.exported_paths))))
            if not export.complete:
                return PipelineExecutionResult(
                    False, sidecar_paths=sidecars, failure_stage="Untertitel-Export",
                    failure_reason=export.failure_summary() or "Sidecar-Export unvollständig.",
                )
        return PipelineExecutionResult.succeeded(
            sidecar_paths=sidecars,
            externalized_subtitle_stream_indices=externalized_subtitle_stream_indices,
        )

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
