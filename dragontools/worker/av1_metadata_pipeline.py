# -*- coding: utf-8 -*-
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

from ..core.media_analyzer import analyze_media, inspect_dynamic_hdr_with_mediainfo
from ..core.media_metadata import normalize_video_codec
from .hdr10_color import HDR10_OUTPUT_ARGS
from .standard_pipeline_runner import _clear_reencoded_video_stat_tags
from .subtitle_sidecar_service import SubtitleSidecarService
from .workflow_models import PipelineExecutionRequest, PipelineExecutionResult


class _AV1MetadataPipelineBase:
    """Gemeinsame, fail-closed Basis fuer die AV1-HDR-Metadatenpfade (Beta)."""

    feature_name = "AV1 HDR-Metadaten"
    failure_stage = "AV1-Metadaten"

    def __init__(
        self,
        *,
        tools,
        progress_runner,
        temp_state,
        log: Callable[[str, str], None] | None = None,
        subtitle_rules: dict | None = None,
        worker=None,
    ) -> None:
        self._tools = tools
        self._progress_runner = progress_runner
        self._temp_state = temp_state
        self._log_fn = log or (lambda *_args, **_kwargs: None)
        self._subtitle_service = SubtitleSidecarService(
            ffmpeg_path=tools.ffmpeg,
            subtitle_rules=dict(subtitle_rules or {}),
            log=self._log,
            worker=worker,
        )

    def _log(self, message: str, level: str = "info") -> None:
        self._log_fn(message, level)

    def _fail(self, reason: str, *, command: list[str] | None = None, output: str = "") -> PipelineExecutionResult:
        command_text = subprocess.list2cmdline(command) if command else ""
        self._temp_state.record_failure(
            reason=reason,
            stage=self.failure_stage,
            tool=Path(self._tools.ffmpeg).name,
            command=command_text,
            output=output,
        )
        self._log(f"❌ {reason}", "error")
        return PipelineExecutionResult(
            success=False,
            failure_reason=reason,
            failure_stage=self.failure_stage,
            tool_output=output,
            tool=Path(self._tools.ffmpeg).name,
            command=command_text,
        )

    def _ffmpeg_help_contains(self, encoder: str, token: str) -> tuple[bool, str]:
        cmd = [self._tools.ffmpeg, "-hide_banner", "-h", f"encoder={encoder}"]
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                timeout=20,
                check=False,
            )
        except Exception as exc:
            return False, str(exc)
        output = result.stdout or ""
        return result.returncode == 0 and token.lower() in output.lower(), output[-6000:]

    @staticmethod
    def _has_geometry_change(plan) -> bool:
        if getattr(plan, "crop", None):
            return True
        args = [str(value).lower() for value in (getattr(plan, "vf_args", None) or [])]
        joined = " ".join(args)
        return "scale=" in joined or "scale_cuda=" in joined or "scale_qsv=" in joined

    def _base_command(self, request: PipelineExecutionRequest, video_args: list[str]) -> list[str]:
        plan = request.plan
        output_args = ["-map_metadata", "0"] + _clear_reencoded_video_stat_tags()
        if str(request.container).lower() in {"mp4", "m4v", "mov"}:
            output_args += ["-movflags", "+faststart"]
        return (
            [self._tools.ffmpeg, "-y", "-loglevel", "error"]
            + list(getattr(plan, "audio_input_args", []) or [])
            + ["-i", request.input_path]
            + list(plan.vf_args)
            + video_args
            + list(plan.audio_args)
            + list(plan.sn)
            + output_args
            + [request.output_path]
        )

    def _run_encode(self, request: PipelineExecutionRequest, video_args: list[str]) -> PipelineExecutionResult | None:
        cmd = self._base_command(request, video_args)
        self._temp_state.last_tool = Path(self._tools.ffmpeg).name
        self._temp_state.last_command = subprocess.list2cmdline(cmd)
        rc = self._progress_runner(cmd, request.input_path, request.duration_ms)
        if int(rc) != 0:
            return self._fail(
                f"{self.feature_name}: FFmpeg-Encoding fehlgeschlagen; Metadaten werden nicht als erhalten gemeldet.",
                command=cmd,
                output=self._temp_state.stderr,
            )
        return None

    def _export_mp4_sidecars(self, request: PipelineExecutionRequest) -> tuple[tuple[str, ...], PipelineExecutionResult | None]:
        if str(request.container).lower() != "mp4":
            return (), None
        export = self._subtitle_service.export_sidecars_result(
            input_path=request.input_path,
            output_base=Path(request.output_path).with_suffix(""),
            media_info=request.media_info,
            file_override=request.override,
        )
        sidecars = tuple(export.exported_paths)
        if not export.complete:
            return sidecars, self._fail(
                export.failure_summary() or "AV1-Metadatenpfad: Sidecar-Export unvollständig."
            )
        return sidecars, None

    def _fallback_analysis(self, output_path: str):
        try:
            return analyze_media(output_path, self._tools)
        except Exception as exc:
            self._log(f"⚠️ Finale AV1-Metadatenanalyse per ffprobe-Fallback fehlgeschlagen: {exc}", "warn")
            return None


class AV1DolbyVisionPipeline(_AV1MetadataPipelineBase):
    """AV1 Dolby Vision Profile 10 via FFmpeg/libsvtav1 (Beta, CPU-only)."""

    feature_name = "AV1 Dolby Vision Profile 10"
    failure_stage = "AV1-DV10"

    def execute(self, request: PipelineExecutionRequest) -> PipelineExecutionResult:
        plan = request.plan
        if plan is None:
            return self._fail("AV1-DV10: Encode-Plan fehlt.")
        if normalize_video_codec(request.codec) != "av1":
            return self._fail("AV1-DV10 benötigt Zielcodec AV1.")
        encoder = str((request.encoder_options or {}).get("encoder", "cpu") or "cpu").lower()
        if encoder != "cpu":
            return self._fail(
                "AV1-DV10 Beta benötigt derzeit CPU/SVT-AV1. NVENC/QSV/AMF werden nicht verwendet, "
                "weil DragonTools dort noch keinen verifizierten DV-Metadatenwrite besitzt."
            )

        source_codec = normalize_video_codec(getattr(getattr(request.media_info, "primary_video", None), "codec", ""))
        if source_codec not in {"hevc", "av1"}:
            return self._fail("AV1-DV10 unterstützt derzeit nur HEVC- oder AV1-Dolby-Vision-Quellen.")
        profile = getattr(request.media_info, "dv_profile_major", None)
        try:
            profile_int = int(profile) if profile not in (None, "") else None
        except (TypeError, ValueError):
            profile_int = None
        if profile_int == 7:
            return self._fail(
                "AV1-DV10 Beta lehnt Dolby Vision Profil 7 ab: Enhancement-Layer/FEL/MEL kann im "
                "aktuellen Single-Layer-AV1-Pfad nicht sicher erhalten werden."
            )
        if profile_int not in {5, 8, 10}:
            return self._fail(
                f"AV1-DV10 Beta benötigt ein eindeutig erkanntes DV-Profil 5, 8 oder 10; erkannt: {profile_int or 'unbekannt'}."
            )
        if self._has_geometry_change(plan):
            return self._fail(
                "AV1-DV10 Beta: Crop oder Skalierung ist noch gesperrt, weil die RPU-Active-Area "
                "dafür noch nicht AV1-spezifisch synchronisiert wird."
            )
        burn_sub = getattr(plan, "burn_sub_or_vf", None)
        if burn_sub and not isinstance(burn_sub, list):
            return self._fail(
                "AV1-DV10 Beta: Untertitel-Burn-In ist noch gesperrt, weil eingebrannte Bildinhalte "
                "noch nicht gegen die bildabhängigen Dolby-Vision-Metadaten abgesichert sind."
            )

        supported, help_output = self._ffmpeg_help_contains("libsvtav1", "dolbyvision")
        if not supported:
            return self._fail(
                "AV1-DV10: Das konfigurierte FFmpeg/libsvtav1 bietet keine 'dolbyvision'-Option. "
                "Bitte einen aktuellen FFmpeg-Full-Build verwenden.",
                output=help_output,
            )

        # FFmpeg konfiguriert DOVI bei AV1 als Profile 10. P5 bleibt dabei als
        # proprietaerer IPTPQc2-Basislayer erhalten; P8/P10 erhalten HDR10-Basis-Tags.
        video_args = [
            "-c:v", "libsvtav1",
            "-crf", str(request.crf),
            "-preset", str(request.preset or "6"),
            "-pix_fmt", "yuv420p10le",
            "-dolbyvision", "1",
        ]
        if profile_int != 5:
            video_args += list(HDR10_OUTPUT_ARGS)

        self._log(
            f"🧪 AV1-DV10 Beta: native FFmpeg/libsvtav1-Pipeline gestartet (Quelle P{profile_int}, CPU, 10-Bit).",
            "info",
        )
        failed = self._run_encode(request, video_args)
        if failed is not None:
            return failed

        inspection = inspect_dynamic_hdr_with_mediainfo(request.output_path, self._tools)
        dv_ok = bool(inspection.dolby_vision)
        out_profile = inspection.dolby_vision_profile
        if not dv_ok:
            fallback = self._fallback_analysis(request.output_path)
            if fallback is not None:
                dv_ok = bool(getattr(fallback, "has_dv", False))
                out_profile = getattr(fallback, "dv_profile", None) or getattr(fallback, "dolby_vision_profile", None)
        if not dv_ok:
            return self._fail("AV1-DV10: finale Dolby-Vision-Verifikation fehlgeschlagen.")
        try:
            out_major = int(str(out_profile).split(".", 1)[0]) if out_profile not in (None, "", "Ja") else None
        except (TypeError, ValueError):
            out_major = None
        if out_major is not None and out_major != 10:
            return self._fail(f"AV1-DV10: finales Dolby-Vision-Profil ist P{out_major} statt P10.")
        if out_major is None:
            self._log("⚠️ AV1-DV10 erkannt, aber MediaInfo/ffprobe konnte Profil 10 nicht numerisch bestätigen.", "warn")

        sidecars, sidecar_failure = self._export_mp4_sidecars(request)
        if sidecar_failure is not None:
            return sidecar_failure
        self._log("✅ AV1-DV10: Dolby Vision nach finalem Mux verifiziert.", "info")
        return PipelineExecutionResult.succeeded(sidecar_paths=sidecars, verified_dolby_vision=True)


class AV1HDR10PlusPipeline(_AV1MetadataPipelineBase):
    """AV1 HDR10+ via FFmpeg/libaom-av1 T.35/OBU passthrough (Beta, CPU-only)."""

    feature_name = "AV1 HDR10+"
    failure_stage = "AV1-HDR10+"

    @staticmethod
    def _cpu_used(preset: object) -> int:
        try:
            # Bestehende AV1-Presets stammen aus SVT (0..13). Fuer libaom wird
            # eine konservative 0..8-Speedstufe verwendet.
            return max(0, min(8, int(str(preset))))
        except (TypeError, ValueError):
            return 6

    def execute(self, request: PipelineExecutionRequest) -> PipelineExecutionResult:
        plan = request.plan
        if plan is None:
            return self._fail("AV1-HDR10+: Encode-Plan fehlt.")
        if normalize_video_codec(request.codec) != "av1":
            return self._fail("AV1-HDR10+ benötigt Zielcodec AV1.")
        encoder = str((request.encoder_options or {}).get("encoder", "cpu") or "cpu").lower()
        if encoder != "cpu":
            return self._fail(
                "AV1-HDR10+ Beta benötigt derzeit CPU/libaom-av1. NVENC/QSV/AMF werden nicht verwendet, "
                "weil DragonTools dort noch keinen verifizierten HDR10+-T.35-Write besitzt."
            )

        supported, help_output = self._ffmpeg_help_contains("libaom-av1", "libaom")
        if not supported:
            return self._fail(
                "AV1-HDR10+: Das konfigurierte FFmpeg enthält keinen nutzbaren libaom-av1-Encoder.",
                output=help_output,
            )

        video_args = [
            "-c:v", "libaom-av1",
            "-crf", str(request.crf),
            "-b:v", "0",
            "-cpu-used", str(self._cpu_used(request.preset)),
            "-pix_fmt", "yuv420p10le",
        ] + list(HDR10_OUTPUT_ARGS)
        self._log(
            "🧪 AV1-HDR10+ Beta: native FFmpeg/libaom-av1-T.35-Pipeline gestartet (CPU, 10-Bit).",
            "info",
        )
        failed = self._run_encode(request, video_args)
        if failed is not None:
            return failed

        inspection = inspect_dynamic_hdr_with_mediainfo(request.output_path, self._tools)
        hdrplus_ok = bool(inspection.hdr10plus)
        if not hdrplus_ok:
            fallback = self._fallback_analysis(request.output_path)
            if fallback is not None:
                hdrplus_ok = bool(
                    getattr(fallback, "has_hdrplus", False)
                    or getattr(fallback, "has_hdr10plus", False)
                )
        if not hdrplus_ok:
            return self._fail("AV1-HDR10+: finale HDR10+-Verifikation fehlgeschlagen.")

        sidecars, sidecar_failure = self._export_mp4_sidecars(request)
        if sidecar_failure is not None:
            return sidecar_failure
        self._log("✅ AV1-HDR10+: dynamische Metadaten nach finalem Mux verifiziert.", "info")
        return PipelineExecutionResult.succeeded(sidecar_paths=sidecars, verified_hdr10plus=True)
