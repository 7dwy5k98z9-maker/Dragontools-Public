# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from ..core.codec_utils import normalize_target_codec


@dataclass(frozen=True)
class HDRPlusEncoderConfig:
    """Jobbezogene Encoderkonfiguration des HDR10+-Pfads.

    Die Konfiguration wird pro Pipeline-Auftrag erzeugt und nicht in einem
    langlebigen Helper mutiert. ``encoder_options`` wird defensiv kopiert und
    read-only exponiert, damit ein Auftrag den nächsten nicht beeinflusst.
    """

    codec: str
    crf: int | str
    preset: str
    encoder_options: Mapping[str, Any]

    @classmethod
    def create(
        cls,
        *,
        codec: str,
        crf: int | str,
        preset: str,
        encoder_options: Mapping[str, Any] | None,
    ) -> "HDRPlusEncoderConfig":
        return cls(
            codec=normalize_target_codec(codec),
            crf=crf,
            preset=str(preset or ""),
            encoder_options=MappingProxyType(dict(encoder_options or {})),
        )

    def mutable_encoder_options(self) -> dict[str, Any]:
        return dict(self.encoder_options)


@dataclass(frozen=True)
class HDRPlusExecutionContext:
    """Alle Daten eines einzelnen HDR10+-Pipeline-Auftrags."""

    input_path: str
    output_path: str
    media_info: Any
    vf_args: tuple[Any, ...]
    audio_args: tuple[Any, ...]
    audio_input_args: tuple[Any, ...]
    subtitle_args: tuple[Any, ...]
    crop: str | None
    container: str
    override: Mapping[str, Any]
    encoder: HDRPlusEncoderConfig

    @classmethod
    def create(
        cls,
        *,
        input_path: str,
        output_path: str,
        media_info: Any,
        vf_args: list | tuple | None,
        audio_args: list | tuple | None,
        audio_input_args: list | tuple | None,
        subtitle_args: list | tuple | None,
        crop: str | None,
        container: str,
        override: Mapping[str, Any] | None,
        encoder: HDRPlusEncoderConfig,
    ) -> "HDRPlusExecutionContext":
        return cls(
            input_path=str(input_path),
            output_path=str(output_path),
            media_info=media_info,
            vf_args=tuple(vf_args or ()),
            audio_args=tuple(audio_args or ()),
            audio_input_args=tuple(audio_input_args or ()),
            subtitle_args=tuple(subtitle_args or ()),
            crop=crop,
            container=str(container or "mkv").lower(),
            override=MappingProxyType(dict(override or {})),
            encoder=encoder,
        )


@dataclass(frozen=True)
class HDRPlusPipelineOutcome:
    success: bool
    verified_hdr10plus: bool = False
    sidecar_paths: tuple[str, ...] = ()
