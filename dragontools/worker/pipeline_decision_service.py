# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Protocol

from ..core.codec_utils import normalize_target_codec
from ..core.models import TargetCodec
from ..core.settings import (
    SET_KEY_PRESERVE_DV,
    SET_KEY_PRESERVE_HDRPLUS,
    SET_KEY_AV1_PRESERVE_DV,
    SET_KEY_AV1_PRESERVE_HDRPLUS,
    SET_KEY_OUTPUT_CONTAINER_STANDARD, SET_KEY_OUTPUT_CONTAINER_DV,
    DEFAULT_OUTPUT_CONTAINER_STANDARD, DEFAULT_OUTPUT_CONTAINER_DV,
    settings_bool, settings_text,
)
from ..core.type_utils import _safe_bool
from ..rules.pipeline_selector import resolve_pipeline_context
from .archive_service import ArchiveService


class SettingsLike(Protocol):
    def value(self, key: str, default=None, type=None): ...


class PipelineDecisionService:
    """Kapselt Policy-Auswertung, Pipeline-Auswahl, Codec-Logging und Archivierung."""

    def __init__(
        self,
        *,
        codec: str,
        encoder_options: dict,
        file_overrides: dict,
        settings: SettingsLike,
        logger,
        archive_service: ArchiveService | None = None,
    ) -> None:
        self._codec = normalize_target_codec(codec)
        self._encoder_options = encoder_options
        self._file_overrides = file_overrides
        self._settings = settings
        self._logger = logger
        self._archive_service = archive_service
        self.last_selection: dict | None = None

    def select_pipeline_context(self, input_path: str, media_info, file_override: dict | None = None) -> tuple[str, str]:
        if self._codec in {TargetCodec.H265.value, TargetCodec.AV1.value}:
            if self._codec == TargetCodec.AV1.value:
                dv_key = SET_KEY_AV1_PRESERVE_DV
                hdr_key = SET_KEY_AV1_PRESERVE_HDRPLUS
            else:
                dv_key = SET_KEY_PRESERVE_DV
                hdr_key = SET_KEY_PRESERVE_HDRPLUS
            stored_dv = settings_bool(self._settings, dv_key, True)
            stored_hdrplus = settings_bool(self._settings, hdr_key, True)
            global_preserve_dv = _safe_bool(
                self._encoder_options.get("preserve_dv", stored_dv), stored_dv
            )
            global_preserve_hdrplus = _safe_bool(
                self._encoder_options.get("preserve_hdrplus", stored_hdrplus), stored_hdrplus
            )
        else:
            global_preserve_dv = False
            global_preserve_hdrplus = False

        selection = resolve_pipeline_context(
            media_info,
            codec=self._codec,
            file_override=(self._file_overrides.get(input_path) if file_override is None else file_override),
            global_preserve_dv=global_preserve_dv,
            global_preserve_hdrplus=global_preserve_hdrplus,
            standard_container=settings_text(
                self._settings, SET_KEY_OUTPUT_CONTAINER_STANDARD, DEFAULT_OUTPUT_CONTAINER_STANDARD,
                allowed=("mkv", "mp4"),
            ),
            dv_container=settings_text(
                self._settings, SET_KEY_OUTPUT_CONTAINER_DV, DEFAULT_OUTPUT_CONTAINER_DV,
                allowed=("mkv", "mp4"),
            ),
        )
        self.last_selection = dict(selection)

        source_codec = selection["source_codec"]
        per_file_dv = selection["per_file_preserve_dv"]
        per_file_hdp = selection["per_file_preserve_hdrplus"]
        should_archive: bool = bool(selection.get("should_archive", False))
        archive_reason: str | None = selection.get("archive_reason")  # type: ignore[assignment]

        self._logger.info(self._source_summary(media_info, source_codec))

        # Capability-Entscheidungen mit dem tatsächlichen Grund loggen. Dadurch
        # wird ein inkompatibler Zielcodec nicht fälschlich als Quellcodec-Problem erklärt.
        capability_warnings = list(selection.get("capability_warnings") or [])
        for warning in capability_warnings:
            self._logger.info(f"⚠️  {warning}")

        # Bewusste Policy-Entscheidungen sind keine Warnungen. Sie werden
        # zusätzlich im sichtbaren Kurzlog ausgegeben, damit z. B. die
        # AV1-Priorität DV vor HDR10+ sofort nachvollziehbar ist.
        for info in list(selection.get("policy_infos") or []):
            info_short = getattr(self._logger, "info_short", None)
            if callable(info_short):
                info_short(str(info))
            else:
                self._logger.info(str(info))

        # Policy-Zusammenfassung nur loggen, wenn sie für die Datei relevant ist.
        eff_dv = bool(selection["effective_preserve_dv"])
        eff_hdp = bool(selection["effective_preserve_hdrplus"])
        src_dv = "per-Datei-Override" if per_file_dv is not None else "globale Einstellung"
        src_hdp = "per-Datei-Override" if per_file_hdp is not None else "globale Einstellung"
        source_has_dv = bool(getattr(media_info, "has_dv", False))
        source_has_hdrplus = bool(
            getattr(media_info, "has_hdrplus", False)
            or getattr(media_info, "has_hdr10plus", False)
        )
        if source_has_dv or source_has_hdrplus or per_file_dv is not None or per_file_hdp is not None:
            dv_policy = (
                f"DV erhalten {eff_dv} ({src_dv})"
                if source_has_dv
                else "DV: nicht in Quelle vorhanden"
            )
            hdrplus_policy = (
                f"HDR10+ erhalten {eff_hdp} ({src_hdp})"
                if source_has_hdrplus
                else "HDR10+: nicht in Quelle vorhanden"
            )
            self._logger.info(f"Policy: {dv_policy} | {hdrplus_policy}")

        # ----------------------------------------------------------------
        # Archivierung ausführen (vor Verarbeitung, bei Fehler abbrechen)
        # ----------------------------------------------------------------
        if should_archive:
            reason = archive_reason or "Metadaten können nicht erhalten werden"
            self._logger.info(f"📦 Quelldatei wird archiviert: {reason}")
            if self._archive_service is None:
                msg = (
                    "ArchiveService nicht verfügbar – Archivierung kann nicht "
                    "durchgeführt werden. Verarbeitung wird abgebrochen."
                )
                self._logger.info(f"❌ {msg}")
                raise RuntimeError(msg)
            # archive_original wirft RuntimeError bei Fehler → Workflow bricht sauber ab
            self._archive_service.archive_original(input_path, reason)

        # ----------------------------------------------------------------
        # Pipeline und Container zurückgeben
        # ----------------------------------------------------------------
        selected_pipeline = selection["pipeline"]
        pipeline = selected_pipeline.value if hasattr(selected_pipeline, "value") else str(selected_pipeline)
        container = str(selection["container"])
        return pipeline, container

    @staticmethod
    def _source_summary(media_info, source_codec: str) -> str:
        video = getattr(media_info, "primary_video", None)
        width = getattr(video, "width", None)
        height = getattr(video, "height", None)
        resolution = f"{width}×{height}" if width and height else "Auflösung unbekannt"
        flags: list[str] = []
        if getattr(media_info, "has_dv", False):
            flags.append(
                f"Dolby Vision Profil {getattr(media_info, 'dolby_vision_profile', None) or '?'}"
            )
        if getattr(media_info, "has_hdrplus", False):
            flags.append("HDR10+")
        if not flags:
            flags.append("HDR" if getattr(media_info, "is_hdr", False) else "SDR")
        audio_count = len(getattr(media_info, "audio_streams", []) or [])
        sub_count = len(getattr(media_info, "subtitle_streams", []) or [])
        return (
            f"Quelle: {str(source_codec or '?').upper()} | {resolution} | "
            f"{' | '.join(flags)} | Audio: {audio_count} | Untertitel: {sub_count}"
        )
