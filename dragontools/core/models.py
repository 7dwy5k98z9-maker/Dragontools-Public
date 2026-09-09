from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .file_override_normalization import normalize_override_dict

class JobStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TargetCodec(str, Enum):
    """Ziel-Videocodec für Encoding-Jobs.

    str-Enum: Werte serialisieren als Plain-String ("h265", "h264", "av1"),
    damit QSettings, JSON-Profile und ConversionJob.codec rueckwaertskompatibel
    bleiben. Vergleiche mit rohen Strings funktionieren weiterhin (== prüft Wert).
    """
    H265 = "h265"
    H264 = "h264"
    AV1  = "av1"


class Pipeline(str, Enum):
    """Konvertierungs-Pipeline-Key.

    Steuert, welcher Verarbeitungspfad gewählt wird:
      STANDARD – normaler ffmpeg-Encode ohne HDR-Spezialbehandlung
      DV          – HEVC Dolby-Vision-Workflow
      HDRPLUS     – HEVC HDR10+-Workflow
      AV1_DV      – AV1 Dolby Vision Profile 10 (Beta)
      AV1_HDRPLUS – AV1 HDR10+ (Beta)
    """
    STANDARD    = "standard"
    DV          = "dv"
    HDRPLUS     = "hdrplus"
    AV1_DV      = "av1_dv"
    AV1_HDRPLUS = "av1_hdrplus"

@dataclass(slots=True)
class SubtitleOverride:
    """Legacy-Brücke für ältere Burn-Mode-Semantik."""
    burn_mode: str = "auto"
    burn_stream_index: int | None = None

@dataclass(slots=True)
class AudioStream:
    index: int
    language: str | None
    forced: bool
    title: str | None
    codec: str
    channels: int
    channel_layout: str | None = None
    bitrate: int | None = None

@dataclass(slots=True)
class SubtitleStream:
    index: int
    language: str | None
    forced: bool
    title: str | None
    codec: str
    event_count: int | None = None
    duration_s: float | None = None

@dataclass(slots=True)
class VideoStream:
    index: int
    codec: str
    width: int
    height: int
    hdr_format: str | None = None
    has_hdr10plus: bool = False
    has_dolby_vision: bool = False
    profile: str | None = None
    pix_fmt: str | None = None
    bit_depth: int | None = None
    color_space: str | None = None
    color_transfer: str | None = None
    color_primaries: str | None = None
    duration_s: float | None = None
    frame_count: int | None = None
    frame_rate: str | None = None
    frame_rate_mode: str | None = None

@dataclass(slots=True)
class MediaInfo:
    path: str
    audio_streams: list[AudioStream]
    subtitle_streams: list[SubtitleStream]
    video_streams: list[VideoStream]
    duration_s: float = 0.0
    size_bytes: int = 0
    is_hdr: bool = False
    has_hdr10plus: bool = False

    # ---------------------------------------------------------------------------
    # Legacy-Feld (rueckwaertskompatibel): "5", "7", "8", "Ja" oder None
    # ---------------------------------------------------------------------------
    dolby_vision_profile: str | None = None

    # ---------------------------------------------------------------------------
    # Erweiterte Dolby-Vision-Felder (neu)
    # ---------------------------------------------------------------------------
    # Ob DV erkannt wurde (True auch wenn Profil unbekannt)
    dolby_vision: bool = False
    # Profilnummer als String ("5", "7", "8") oder None bei unbekanntem Profil
    dv_profile: str | None = None
    # Profilnummer als int (5, 7, 8) oder None – für programmatische Auswertung
    dv_profile_major: int | None = None
    # Codec-Tag, z.B. "dvhe.05.06", "dvhe.08.06", "dvh1.08.06"
    dv_codec_tag: str | None = None
    # DV Level aus HDR_Format_Level, z.B. "6"
    dv_level: str | None = None
    # Rohstring aus HDR_Format (z.B. "Dolby Vision, Version 1.0, Profile 5, …")
    dv_format_raw: str | None = None
    # Rohstring aus HDR_Format_Profile (z.B. "dvhe.05", "dvhe.05.06")
    hdr_format_profile_raw: str | None = None

    # ---------------------------------------------------------------------------
    # Farb-Metadaten (neu, aus primaerem Video-Track)
    # ---------------------------------------------------------------------------
    color_range: str | None = None
    transfer_characteristics: str | None = None
    matrix_coefficients: str | None = None

    analysis_source: str = "Unbekannt"
    analysis_warnings: list[str] = field(default_factory=list)

    @property
    def primary_video(self) -> VideoStream | None:
        return self.video_streams[0] if self.video_streams else None

    @property
    def has_dv(self) -> bool:
        return bool(self.dolby_vision) or any(
            v.hdr_format == "dolby_vision" or getattr(v, "has_dolby_vision", False)
            for v in self.video_streams
        )

    @property
    def has_hdrplus(self) -> bool:
        return bool(self.has_hdr10plus) or any(
            v.hdr_format == "hdr10plus" or getattr(v, "has_hdr10plus", False)
            for v in self.video_streams
        )

    def dv_profile_label(self) -> str:
        """Gibt einen lesbaren Profilstring für Logging/UI zurück.

        Beispiele:
          "Profil: 5 / dvhe.05.06"
          "Profil: 8 / dvhe.08.06"
          "Profil: unbekannt"
        """
        if not self.dolby_vision:
            return "kein DV"
        parts: list[str] = []
        if self.dv_profile is not None:
            parts.append(self.dv_profile)
        if self.dv_codec_tag:
            parts.append(self.dv_codec_tag)
        if parts:
            return "Profil: " + " / ".join(parts)
        return "Profil: unbekannt"

@dataclass(slots=True)
class ConversionJob:
    id: str
    input_path: str
    output_path: str | None
    codec: str
    pipeline: str = "standard"
    profile_key: str = "film"
    crf: int = 23
    preset: str = "medium"
    scale: str | None = None
    overwrite_original: bool = False
    subtitle_override: SubtitleOverride | None = None
    planned_move_target: str | None = None
    status: JobStatus = JobStatus.PENDING
    file_overrides: dict[str, Any] = field(default_factory=dict)
    crop_filter: str | None = None   # z.B. "crop=3840:1632:0:276" – für DV Level 5

    @property
    def input_name(self) -> str:
        return Path(self.input_path).name
