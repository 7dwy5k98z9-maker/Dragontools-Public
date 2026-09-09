# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..core.media_metadata import normalize_video_codec
from .dv_subtitle_mux_service import DVSubtitleMuxService, dv_subtitle_storage
from .hdrplus_encode_service import HDRPlusEncodeService
from .hdrplus_runtime_models import HDRPlusExecutionContext, HDRPlusPipelineOutcome
from .subtitle_sidecar_service import SubtitleSidecarService

_SUPPORTED_HDR10PLUS_SOURCE_CODECS = {"hevc"}


@dataclass(frozen=True)
class HDRPlusPipelineHooks:
    """Explizite Kompatibilitäts-/Service-Grenze zur Fassade.

    Die Hooks werden pro Lauf gebunden. Damit bleiben bestehende private
    Test-/Kompatibilitätswrapper monkeypatchbar, ohne dass der Coordinator eine
    Owner-Referenz oder private Cross-Class-Aufrufe benötigt.
    """

    extract_hevc_annexb: Callable[[str, str], bool]
    extract_metadata: Callable[[str, str], bool]
    inject_metadata: Callable[[str, str, str], bool]
    mux_output: Callable[..., bool]
    run_mux_tool: Callable[..., bool]
    verify_final: Callable[[str, Path], bool]
    cleanup_tmp_sub: Callable[[str], None]


@dataclass(frozen=True)
class HDRPlusPipelinePaths:
    root: Path
    metadata_json: Path
    encoded_hevc: Path
    stream_donor: Path
    injected_hevc: Path
    metadata_fallback_hevc: Path

    @classmethod
    def create(cls, root: Path) -> "HDRPlusPipelinePaths":
        return cls(
            root=root,
            metadata_json=root / "metadata.json",
            encoded_hevc=root / "encoded.hevc",
            stream_donor=root / "streams.mkv",
            injected_hevc=root / "injected.hevc",
            metadata_fallback_hevc=root / "source_metadata.hevc",
        )


class HDRPlusPipelineCoordinator:
    """Orchestriert ausschließlich den fünfstufigen HDR10+-Ablauf."""

    def __init__(
        self,
        *,
        encode_service: HDRPlusEncodeService,
        subtitle_service: SubtitleSidecarService,
        subtitle_mux_service: DVSubtitleMuxService,
        subtitle_rules: dict,
        log: Callable[[str, str], None],
    ) -> None:
        self._encode = encode_service
        self._subtitle_service = subtitle_service
        self._subtitle_mux_service = subtitle_mux_service
        self._subtitle_rules = dict(subtitle_rules or {})
        self._log = log

    def run(
        self,
        context: HDRPlusExecutionContext,
        hooks: HDRPlusPipelineHooks,
    ) -> HDRPlusPipelineOutcome:
        try:
            if not self._preflight(context, hooks):
                return HDRPlusPipelineOutcome(False)

            temp_parent = Path(context.output_path).parent
            temp_parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="dragontools_hdr10plus_", dir=temp_parent) as tmp:
                paths = HDRPlusPipelinePaths.create(Path(tmp))
                self._log_start(context)

                if not self._step_extract_metadata(context, paths, hooks):
                    return self._failed_step(context, hooks, 1)
                if not self._step_encode(context, paths):
                    return self._failed_step(context, hooks, 2)
                hooks.cleanup_tmp_sub(context.input_path)
                if not self._step_inject(paths, hooks):
                    return self._failed_step(context, hooks, 3)

                subtitle_tracks = self._prepare_internal_mp4_subtitles(context, paths, hooks)
                if subtitle_tracks is None:
                    hooks.cleanup_tmp_sub(context.input_path)
                    return HDRPlusPipelineOutcome(False)
                if not self._step_mux(context, paths, hooks, subtitle_tracks):
                    return self._failed_step(context, hooks, 4)
                if not self._validate_output(context):
                    hooks.cleanup_tmp_sub(context.input_path)
                    return HDRPlusPipelineOutcome(False)
                if not self._step_verify(context, paths, hooks):
                    return self._failed_step(context, hooks, 5)

                sidecars = self._export_mp4_sidecars(context)
                if sidecars is None:
                    hooks.cleanup_tmp_sub(context.input_path)
                    return HDRPlusPipelineOutcome(False)

                hooks.cleanup_tmp_sub(context.input_path)
                self._log(
                    f"HDR10+: Spezialpfad erfolgreich abgeschlossen -> {Path(context.output_path).name}",
                    "info",
                )
                return HDRPlusPipelineOutcome(
                    True,
                    verified_hdr10plus=True,
                    sidecar_paths=tuple(sidecars),
                )
        except Exception:
            hooks.cleanup_tmp_sub(context.input_path)
            self._log(
                f"❌ Unbehandelte Ausnahme in _convert_hdrplus() bei {Path(context.input_path).name}",
                "error",
            )
            self._log(traceback.format_exc(), "error")
            return HDRPlusPipelineOutcome(False)

    def _preflight(self, context: HDRPlusExecutionContext, hooks: HDRPlusPipelineHooks) -> bool:
        if context.encoder.codec != "h265":
            hooks.cleanup_tmp_sub(context.input_path)
            self._log(
                f"❌ HDR10+: Zielcodec '{context.encoder.codec}' ist nicht kompatibel. "
                "Der aktuelle HDR10+-Toolpfad unterstützt nur HEVC/H.265.",
                "error",
            )
            self._log("HDR10+: Abbruch statt Fallback, damit HDR10+ nicht still verloren geht.", "error")
            return False

        primary_video = context.media_info.primary_video
        source_codec = normalize_video_codec(getattr(primary_video, "codec", None))
        if source_codec == "hevc":
            return True

        hooks.cleanup_tmp_sub(context.input_path)
        self._log(
            f"❌ HDR10+: Quellcodec '{source_codec or 'unbekannt'}' wird vom "
            "konfigurierten HEVC-HDR10+-Toolpfad nicht unterstützt. "
            f"Unterstützte Quell-Codecs: {', '.join(sorted(_SUPPORTED_HDR10PLUS_SOURCE_CODECS))}.",
            "error",
        )
        return False

    def _log_start(self, context: HDRPlusExecutionContext) -> None:
        self._log(
            f"HDR10+: Spezialpfad gestartet für {Path(context.input_path).name} (Quell-Codec: HEVC)",
            "info",
        )
        if context.crop:
            self._log(f"HDR10+: aktiver Crop-Filter -> {context.crop}", "info")

    def _step_extract_metadata(
        self,
        context: HDRPlusExecutionContext,
        paths: HDRPlusPipelinePaths,
        hooks: HDRPlusPipelineHooks,
    ) -> bool:
        self._log("HDR10+: Schritt 1/5 -> HDR10+-Metadaten aus Quelle extrahieren", "info")
        input_path = context.input_path
        suffix = Path(input_path).suffix.lower()

        if suffix in {".mkv", ".webm"}:
            # Normalfall: hdr10plus_tool kann Matroska/HEVC direkt lesen. Das spart
            # die mehrere GB große source.hevc-Zwischendatei. Einige formal
            # abspielbare HEVC-Streams werden vom Container-Parser des Tools aber
            # mit Fehlern wie "Invalid PPS index" abgelehnt. In diesem Fall wird
            # der bewährte Annex-B-Weg aus älteren DragonTools-Versionen gezielt
            # als Recovery-Fallback verwendet.
            if hooks.extract_metadata(input_path, str(paths.metadata_json)):
                return True

            self._log(
                "⚠️ HDR10+: Direkter Metadata-Extract aus Matroska fehlgeschlagen; "
                "erneuter Versuch über HEVC-Annex-B.",
                "warn",
            )
        else:
            self._log(
                "HDR10+: Quellcontainer ist nicht Matroska – Metadata-Extract erfolgt über HEVC-Annex-B.",
                "info",
            )

        if not hooks.extract_hevc_annexb(input_path, str(paths.metadata_fallback_hevc)):
            self._log("❌ HDR10+: HEVC-Annex-B-Fallback fehlgeschlagen.", "error")
            return False

        if hooks.extract_metadata(str(paths.metadata_fallback_hevc), str(paths.metadata_json)):
            if suffix in {".mkv", ".webm"}:
                self._log("✅ HDR10+: Metadata-Extract über HEVC-Annex-B-Fallback erfolgreich.", "info")
            return True

        if suffix in {".mkv", ".webm"}:
            self._log(
                "❌ HDR10+: Metadata-Extract ist sowohl direkt aus Matroska als auch über HEVC-Annex-B fehlgeschlagen.",
                "error",
            )
        return False

    def _step_encode(self, context: HDRPlusExecutionContext, paths: HDRPlusPipelinePaths) -> bool:
        self._log(
            "HDR10+: Schritt 2/5 -> direkt nach HEVC encodieren und Begleitstreams vorbereiten",
            "info",
        )
        subtitle_args = context.subtitle_args if context.container == "mkv" else ("-sn",)
        return self._encode.encode(
            input_path=context.input_path,
            encoded_hevc=paths.encoded_hevc,
            stream_donor=paths.stream_donor,
            vf_args=context.vf_args,
            audio_args=context.audio_args,
            audio_input_args=context.audio_input_args,
            subtitle_args=subtitle_args,
            media_info=context.media_info,
            encoder=context.encoder,
        )

    def _step_inject(self, paths: HDRPlusPipelinePaths, hooks: HDRPlusPipelineHooks) -> bool:
        self._log("HDR10+: Schritt 3/5 -> HDR10+-Metadaten injizieren", "info")
        return hooks.inject_metadata(
            str(paths.encoded_hevc),
            str(paths.metadata_json),
            str(paths.injected_hevc),
        )

    def _prepare_internal_mp4_subtitles(
        self,
        context: HDRPlusExecutionContext,
        paths: HDRPlusPipelinePaths,
        hooks: HDRPlusPipelineHooks,
    ):
        if context.container != "mp4" or dv_subtitle_storage("mp4", self._subtitle_rules) != "hybrid":
            return []
        ok, tracks = self._subtitle_mux_service.prepare_internal_mp4_tracks(
            input_path=context.input_path,
            media_info=context.media_info,
            file_override=dict(context.override),
            tmp_dir=paths.root,
            run_fn=lambda cmd: 0 if hooks.run_mux_tool(
                cmd,
                label="HDR10+: MP4-Untertitel vorbereiten",
                tool_name="ffmpeg",
            ) else 1,
        )
        return tracks if ok else None

    def _step_mux(
        self,
        context: HDRPlusExecutionContext,
        paths: HDRPlusPipelinePaths,
        hooks: HDRPlusPipelineHooks,
        subtitle_tracks,
    ) -> bool:
        self._log(f"HDR10+: Schritt 4/5 -> finales {context.container.upper()} muxen", "info")
        kwargs = {"container": context.container, "tmp_dir": paths.root}
        if context.container == "mp4":
            kwargs["subtitle_tracks"] = subtitle_tracks
        return hooks.mux_output(
            str(paths.injected_hevc),
            str(paths.stream_donor) if paths.stream_donor.exists() else "",
            context.output_path,
            **kwargs,
        )

    def _validate_output(self, context: HDRPlusExecutionContext) -> bool:
        output = Path(context.output_path)
        if output.exists() and output.stat().st_size >= 1024:
            return True
        self._log(f"❌ HDR10+: Zieldatei fehlt oder ist unplausibel klein: {output.name}", "error")
        return False

    def _step_verify(
        self,
        context: HDRPlusExecutionContext,
        paths: HDRPlusPipelinePaths,
        hooks: HDRPlusPipelineHooks,
    ) -> bool:
        self._log("HDR10+: Schritt 5/5 -> finale HDR10+-Metadaten semantisch verifizieren", "info")
        return hooks.verify_final(context.output_path, paths.metadata_json)

    def _export_mp4_sidecars(self, context: HDRPlusExecutionContext) -> list[str] | None:
        if context.container != "mp4":
            return []
        export = self._subtitle_service.export_sidecars_result(
            input_path=context.input_path,
            output_base=Path(context.output_path).with_suffix(""),
            media_info=context.media_info,
            file_override=dict(context.override),
        )
        if not export.complete:
            self._log(f"❌ HDR10+ MP4: {export.failure_summary()}", "error")
            return None
        return list(export.exported_paths)

    def _failed_step(
        self,
        context: HDRPlusExecutionContext,
        hooks: HDRPlusPipelineHooks,
        step: int,
    ) -> HDRPlusPipelineOutcome:
        hooks.cleanup_tmp_sub(context.input_path)
        self._log(f"❌ HDR10+: Schritt {step}/5 fehlgeschlagen.", "error")
        return HDRPlusPipelineOutcome(False)
