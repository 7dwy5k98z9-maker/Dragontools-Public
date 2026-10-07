# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import shutil
import tempfile
import traceback
from dataclasses import dataclass
from functools import partial
from .log_dispatch import dispatch_log
from .hdrplus_recovery_archive import preserve_hdrplus_failure
from .hdrplus_workspace import HDRPlusWorkspace, cleanup_subtitle_temporary
from .frame_count_evidence import temporal_mapping_for_filters
from .hdrplus_source_selection import trusted_hdr_primary_index, extract_selected_hdr_video
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..core.media_metadata import normalize_video_codec
from .dv_subtitle_mux_service import DVSubtitleMuxService, dv_subtitle_storage
from .hdrplus_encode_service import HDRPlusEncodeService
from .hdrplus_runtime_models import HDRPlusExecutionContext, HDRPlusPipelineOutcome
from .subtitle_sidecar_service import SubtitleSidecarService
from ..rules.subtitle_rules import any_sidecar_export_enabled

_SUPPORTED_HDR10PLUS_SOURCE_CODECS = {"hevc"}


@dataclass(frozen=True)
class HDRPlusPipelineHooks:
    """Explizite Kompatibilitäts-/Service-Grenze zur Fassade.

    Die Hooks werden pro Lauf gebunden. Damit bleiben bestehende private
    Test-/Kompatibilitätswrapper monkeypatchbar, ohne dass der Coordinator eine
    Owner-Referenz oder private Cross-Class-Aufrufe benötigt.
    """

    extract_hevc_annexb: Callable[..., bool]
    extract_metadata: Callable[[str, str], bool]
    generate_metadata: Callable[[str, str], bool]
    inject_metadata: Callable[[str, str, str], bool]
    mux_output: Callable[..., bool]
    run_mux_tool: Callable[..., bool]
    verify_final: Callable[[str, Path], bool]
    cleanup_tmp_sub: Callable[[str], None]
    extract_interrupted: Callable[[], bool] = lambda: False


@dataclass(frozen=True)
class HDRPlusPipelinePaths:
    root: Path
    metadata_json: Path
    encoded_hevc: Path
    stream_donor: Path
    injected_hevc: Path
    metadata_fallback_hevc: Path
    workspace: HDRPlusWorkspace | None = None

    @classmethod
    def create(cls, root: Path, workspace: HDRPlusWorkspace | None = None) -> "HDRPlusPipelinePaths":
        return cls(
            root=root,
            workspace=workspace,
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
        self._log = partial(dispatch_log, log)

    def run(
        self,
        context: HDRPlusExecutionContext,
        hooks: HDRPlusPipelineHooks,
    ) -> HDRPlusPipelineOutcome:
        workspace: HDRPlusWorkspace | None = None
        paths: HDRPlusPipelinePaths | None = None
        try:
            if not self._preflight(context, hooks):
                return HDRPlusPipelineOutcome(False)

            temp_parent = Path(context.output_path).parent
            temp_parent.mkdir(parents=True, exist_ok=True)
            workspace = HDRPlusWorkspace(temp_parent, "dragontools_hdr10plus_")
            paths = HDRPlusPipelinePaths.create(workspace.root, workspace)
            self._log_start(context)

            if context.generate_hdr10plus:
                if not self._step_encode(context, paths):
                    return self._failed_step(context, hooks, paths, 1)
                cleanup_subtitle_temporary(hooks, context.input_path, self._log)
                if not self._step_generate_metadata(paths, hooks):
                    return self._failed_step(context, hooks, paths, 2)
            else:
                if not self._step_extract_metadata(context, paths, hooks):
                    return self._failed_step(context, hooks, paths, 1)
                if not self._step_encode(context, paths):
                    return self._failed_step(context, hooks, paths, 2)
                cleanup_subtitle_temporary(hooks, context.input_path, self._log)
            if not self._step_inject(paths, hooks):
                return self._failed_step(context, hooks, paths, 3)

            subtitle_tracks = self._prepare_internal_mp4_subtitles(context, paths, hooks)
            if subtitle_tracks is None:
                cleanup_subtitle_temporary(hooks, context.input_path, self._log)
                return self._archive_failure(context, paths, "subtitle_prepare")
            if not self._step_mux(context, paths, hooks, subtitle_tracks):
                return self._failed_step(context, hooks, paths, 4)
            if not self._validate_output(context):
                cleanup_subtitle_temporary(hooks, context.input_path, self._log)
                return self._archive_failure(context, paths, "output_validation")
            if not self._step_verify(context, paths, hooks):
                return self._failed_step(context, hooks, paths, 5)

            sidecars = self._export_mp4_sidecars(context)
            if sidecars is None:
                cleanup_subtitle_temporary(hooks, context.input_path, self._log)
                # Der Medienoutput ist zu diesem Zeitpunkt bereits semantisch
                # verifiziert. Ein Sidecar-Fehler darf ihn daher nicht durch
                # den generischen Failure-Cleanup wieder löschen.
                workspace.mark_persisted()
                return HDRPlusPipelineOutcome(False, preserve_failed_output=True)

            cleanup_subtitle_temporary(hooks, context.input_path, self._log)
            self._log(
                f"HDR10+: Spezialpfad erfolgreich abgeschlossen -> {Path(context.output_path).name}",
                "info",
            )
            workspace.mark_persisted()
            return HDRPlusPipelineOutcome(
                True,
                verified_hdr10plus=True,
                sidecar_paths=tuple(sidecars),
            )
        except Exception:
            cleanup_subtitle_temporary(hooks, context.input_path, self._log)
            self._log(
                f"❌ Unbehandelte Ausnahme in _convert_hdrplus() bei {Path(context.input_path).name}",
                "error",
            )
            self._log(traceback.format_exc(), "error")
            if paths is not None:
                return self._archive_failure(context, paths, "unhandled_exception")
            return HDRPlusPipelineOutcome(False)
        finally:
            if workspace is not None:
                workspace.finish()

    def postprocess_existing_output(
        self,
        context: HDRPlusExecutionContext,
        hooks: HDRPlusPipelineHooks,
        *,
        sidecar_paths: tuple[str, ...] = (),
    ) -> HDRPlusPipelineOutcome:
        """Erzeugt HDR10+ fuer einen bereits erfolgreich erzeugten HEVC-Output.

        Dieser Pfad ist bewusst transaktional: ``context.output_path`` bleibt bis
        nach erfolgreicher semantischer Verifikation unverändert. Erst danach
        ersetzt der Kandidat den bisherigen Standard-/Strip-Output atomar.
        """

        workspace: HDRPlusWorkspace | None = None
        paths: HDRPlusPipelinePaths | None = None
        candidate: Path | None = None
        try:
            if context.encoder.codec != "h265":
                self._log("❌ HDR10+-Postprozess benötigt Zielcodec HEVC/H.265.", "error")
                return HDRPlusPipelineOutcome(False, preserve_failed_output=True)
            if context.container not in {"mkv", "mp4"}:
                self._log(
                    f"❌ HDR10+-Postprozess: Nicht unterstützter Zielcontainer: {context.container or '<leer>'}",
                    "error",
                )
                return HDRPlusPipelineOutcome(False, preserve_failed_output=True)

            output = Path(context.output_path)
            if not output.exists() or output.stat().st_size < 1024:
                self._log("❌ HDR10+-Postprozess: vorhandener Medienoutput fehlt oder ist unplausibel klein.", "error")
                return HDRPlusPipelineOutcome(False)

            workspace = HDRPlusWorkspace(output.parent, "dragontools_hdr10plus_post_")
            paths = HDRPlusPipelinePaths.create(workspace.root, workspace)
            candidate = paths.root / f"candidate.{context.container}"

            self._log("HDR10+-Postprozess: HEVC-Videostream aus fertigem Output extrahieren.", "info")
            if not hooks.extract_hevc_annexb(context.output_path, str(paths.encoded_hevc)):
                return self._archive_failure(
                    context, paths, "post_extract", extra_paths=(candidate,), force_preserve_output=True, include_output=False
                )
            if not self._step_generate_metadata(paths, hooks):
                return self._archive_failure(
                    context, paths, "post_generator", extra_paths=(candidate,), force_preserve_output=True, include_output=False
                )
            if not self._step_inject(paths, hooks):
                return self._archive_failure(
                    context, paths, "post_injection", extra_paths=(candidate,), force_preserve_output=True, include_output=False
                )

            subtitle_tracks = self._prepare_internal_mp4_subtitles(context, paths, hooks)
            if subtitle_tracks is None:
                return self._archive_failure(
                    context, paths, "post_subtitle_prepare", extra_paths=(candidate,), force_preserve_output=True, include_output=False
                )

            mux_kwargs = {"container": context.container, "tmp_dir": paths.root}
            if context.container == "mp4":
                mux_kwargs["subtitle_tracks"] = subtitle_tracks
            if not hooks.mux_output(
                str(paths.injected_hevc),
                context.output_path,
                str(candidate),
                **mux_kwargs,
            ):
                return self._archive_failure(
                    context, paths, "post_mux", extra_paths=(candidate,), force_preserve_output=True, include_output=False
                )
            if not candidate.exists() or candidate.stat().st_size < 1024:
                self._log("❌ HDR10+-Postprozess: Mux-Kandidat fehlt oder ist unplausibel klein.", "error")
                return self._archive_failure(
                    context, paths, "post_output_validation", extra_paths=(candidate,), force_preserve_output=True, include_output=False
                )
            if not hooks.verify_final(str(candidate), paths.metadata_json):
                self._log("❌ HDR10+-Postprozess: finale HDR10+-Verifikation des Kandidaten fehlgeschlagen.", "error")
                return self._archive_failure(
                    context, paths, "post_verify", extra_paths=(candidate,), force_preserve_output=True, include_output=False
                )

            # Kandidat und Ziel liegen absichtlich im selben Dateisystem.
            # os.replace ist damit der transaktionale Commit-Punkt.
            os.replace(candidate, output)
            workspace.mark_persisted()
            cleanup_subtitle_temporary(hooks, context.input_path, self._log)
            self._log("✅ HDR10+-Postprozess erfolgreich verifiziert und atomar installiert.", "info")
            return HDRPlusPipelineOutcome(
                True,
                verified_hdr10plus=True,
                sidecar_paths=tuple(sidecar_paths),
            )
        except Exception:
            cleanup_subtitle_temporary(hooks, context.input_path, self._log)
            self._log("❌ Unbehandelte Ausnahme im HDR10+-Postprozess.", "error")
            self._log(traceback.format_exc(), "error")
            if paths is not None:
                return self._archive_failure(
                    context,
                    paths,
                    "post_unhandled_exception",
                    extra_paths=(candidate,) if candidate is not None else (),
                    force_preserve_output=True, include_output=False,
                )
            return HDRPlusPipelineOutcome(False, preserve_failed_output=True)
        finally:
            if workspace is not None:
                workspace.finish()

    def _preflight(self, context: HDRPlusExecutionContext, hooks: HDRPlusPipelineHooks) -> bool:
        if context.container not in {"mkv", "mp4"}:
            cleanup_subtitle_temporary(hooks, context.input_path, self._log)
            self._log(
                f"❌ HDR10+: Nicht unterstützter Zielcontainer: {context.container or '<leer>'}. "
                "Erlaubt sind ausschließlich MKV oder MP4.",
                "error",
            )
            return False

        if context.encoder.codec != "h265":
            cleanup_subtitle_temporary(hooks, context.input_path, self._log)
            self._log(
                f"❌ HDR10+: Zielcodec '{context.encoder.codec}' ist nicht kompatibel. "
                "Der aktuelle HDR10+-Toolpfad unterstützt nur HEVC/H.265.",
                "error",
            )
            self._log("HDR10+: Abbruch statt Fallback, damit HDR10+ nicht still verloren geht.", "error")
            return False

        if context.generate_hdr10plus:
            # Generated metadata is measured from the freshly encoded HEVC stream,
            # therefore no source-bitstream metadata extraction is required.
            return True

        if temporal_mapping_for_filters(context.vf_args) != 'preserved':
            self._log('❌ HDR10+: Übernommene Metadaten benötigen eine unveränderte Bildfolge.', 'error')
            return False

        primary_video = context.media_info.primary_video
        source_codec = normalize_video_codec(getattr(primary_video, "codec", None))
        if source_codec == "hevc":
            return True

        cleanup_subtitle_temporary(hooks, context.input_path, self._log)
        self._log(
            f"❌ HDR10+: Quellcodec '{source_codec or 'unbekannt'}' wird vom "
            "konfigurierten HEVC-HDR10+-Toolpfad nicht unterstützt. "
            f"Unterstützte Quell-Codecs: {', '.join(sorted(_SUPPORTED_HDR10PLUS_SOURCE_CODECS))}.",
            "error",
        )
        return False

    def _log_start(self, context: HDRPlusExecutionContext) -> None:
        mode = "Generator" if context.generate_hdr10plus else "Preserve"
        self._log(
            f"HDR10+: Spezialpfad gestartet für {Path(context.input_path).name} (Modus: {mode})",
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
        try:
            primary_stream_index = trusted_hdr_primary_index(context.media_info)
        except ValueError as exc:
            self._log(f'❌ HDR10+: {exc}', 'error')
            return False

        raw_video_streams = getattr(context.media_info, "video_streams", None)
        video_streams = list(raw_video_streams or [])
        # Reale MediaInfo-Objekte tragen ``video_streams``. Legacy-/Testadapter
        # stellen teilweise nur ``primary_video`` bereit; dort behalten wir den
        # bisherigen Direktpfad. Sobald mehrere Spuren bekannt sind, ist der
        # Container-Extract aber bewusst verboten.
        direct_container_extract = (
            suffix in {".mkv", ".webm"}
            and (raw_video_streams is None or len(video_streams) == 1)
        )

        if direct_container_extract:
            # Normalfall: hdr10plus_tool kann Matroska/HEVC direkt lesen. Das spart
            # die mehrere GB große source.hevc-Zwischendatei. Einige formal
            # abspielbare HEVC-Streams werden vom Container-Parser des Tools aber
            # mit Fehlern wie "Invalid PPS index" abgelehnt. In diesem Fall wird
            # der bewährte Annex-B-Weg aus älteren DragonTools-Versionen gezielt
            # als Recovery-Fallback verwendet.
            if hooks.extract_metadata(input_path, str(paths.metadata_json)):
                return True
            if hooks.extract_interrupted():
                return False

            self._log(
                "⚠️ HDR10+: Direkter Metadata-Extract aus Matroska fehlgeschlagen; "
                "erneuter Versuch über HEVC-Annex-B.",
                "warn",
            )
        else:
            if suffix in {".mkv", ".webm"} and len(video_streams) > 1:
                self._log(
                    "HDR10+: Mehrere Videospuren erkannt – direkter Container-Extract wird übersprungen, "
                    "damit hdr10plus_tool keine mehrdeutige Spur auswählt.",
                    "info",
                )
            else:
                self._log(
                    "HDR10+: Quellcontainer ist nicht Matroska – Metadata-Extract erfolgt über HEVC-Annex-B.",
                    "info",
                )

        extracted = extract_selected_hdr_video(hooks.extract_hevc_annexb, input_path,
            str(paths.metadata_fallback_hevc), primary_stream_index)

        if not extracted:
            self._log("❌ HDR10+: HEVC-Annex-B-Fallback fehlgeschlagen.", "error")
            return False

        if hooks.extract_metadata(str(paths.metadata_fallback_hevc), str(paths.metadata_json)):
            if suffix in {".mkv", ".webm"}:
                self._log("✅ HDR10+: Metadata-Extract über HEVC-Annex-B-Fallback erfolgreich.", "info")
            return True

        if direct_container_extract:
            self._log(
                "❌ HDR10+: Metadata-Extract ist sowohl direkt aus Matroska als auch über HEVC-Annex-B fehlgeschlagen.",
                "error",
            )
        elif suffix in {".mkv", ".webm"}:
            self._log("❌ HDR10+: Metadata-Extract über den eindeutigen HEVC-Annex-B-Pfad fehlgeschlagen.", "error")
        return False

    def _step_encode(self, context: HDRPlusExecutionContext, paths: HDRPlusPipelinePaths) -> bool:
        step = 1 if context.generate_hdr10plus else 2
        self._log(
            f"HDR10+: Schritt {step}/5 -> finalen HEVC-Videostream encodieren und Begleitstreams vorbereiten",
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

    def _step_generate_metadata(
        self,
        paths: HDRPlusPipelinePaths,
        hooks: HDRPlusPipelineHooks,
    ) -> bool:
        self._log(
            "HDR10+: Schritt 2/5 -> finalen HEVC-Videostream analysieren und hdr10plus.json erzeugen",
            "info",
        )
        return hooks.generate_metadata(str(paths.encoded_hevc), str(paths.metadata_json))

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
        if not any_sidecar_export_enabled(self._subtitle_rules, container=context.container):
            return []
        export = self._subtitle_service.export_sidecars_result(
            input_path=context.input_path,
            output_base=Path(context.output_path).with_suffix(""),
            media_info=context.media_info,
            file_override=dict(context.override),
            container=context.container,
        )
        if not export.complete:
            self._log(f"❌ HDR10+ MP4: {export.failure_summary()}", "error")
            return None
        return list(export.exported_paths)

    def _failed_step(
        self,
        context: HDRPlusExecutionContext,
        hooks: HDRPlusPipelineHooks,
        paths: HDRPlusPipelinePaths,
        step: int,
    ) -> HDRPlusPipelineOutcome:
        cleanup_subtitle_temporary(hooks, context.input_path, self._log)
        self._log(f"❌ HDR10+: Schritt {step}/5 fehlgeschlagen.", "error")
        return self._archive_failure(context, paths, f"step_{step}")

    def _archive_failure(self, context, paths, stage, *, extra_paths=(), force_preserve_output=False, include_output=True):
        return preserve_hdrplus_failure(context, paths, stage, extra_paths=extra_paths,
            force_preserve_output=force_preserve_output, include_output=include_output, log=self._log)
