# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .dv_audio_mux_service import DVExtractedAudioTrack, DVMuxAudioTrack
from .dv_subtitle_mux_service import DVMuxSubtitleTrack


def normalize_dv_profile_major(media_info) -> int | None:
    """Liefert das DV-Hauptprofil robust als ``int``.

    MediaInfo wird normalerweise bereits als int normalisiert. Ältere Cache-
    oder Override-Pfade können aber Strings wie ``"5"``/``"7"``/``"8"``
    enthalten. Für P5 ist eine falsche Typannahme besonders gefährlich, weil
    sonst die notwendige libplacebo-ICtCp-Konvertierung übersprungen würde.
    """
    raw = getattr(media_info, "dv_profile_major", None)
    if raw in (None, ""):
        raw = getattr(media_info, "dv_profile", None)
    if raw in (None, ""):
        return None
    try:
        return int(str(raw).strip().split(".", 1)[0])
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class DVRunRequest:
    input_path: str
    output_path: str
    media_info: object
    vf_args: list
    audio_args: list
    audio_input_args: list
    sn: list
    crop: str | None
    override: dict
    preserve_hdrplus: bool
    container: str
    profile_major: int | None

    @classmethod
    def create(
        cls,
        *,
        input_path: str,
        output_path: str,
        media_info,
        vf_args: list,
        audio_args: list,
        audio_input_args: list | None,
        sn: list,
        crop: str | None,
        override: dict | None,
        preserve_hdrplus: bool,
        container: str = "mp4",
    ) -> "DVRunRequest":
        return cls(
            input_path=input_path,
            output_path=output_path,
            media_info=media_info,
            vf_args=list(vf_args),
            audio_args=list(audio_args),
            audio_input_args=list(audio_input_args or []),
            sn=list(sn),
            crop=crop,
            override=dict(override or {}),
            preserve_hdrplus=bool(preserve_hdrplus),
            container=str(container or "mp4").strip().lower(),
            profile_major=normalize_dv_profile_major(media_info),
        )

    @property
    def is_p5(self) -> bool:
        return self.profile_major == 5

    @property
    def preserve_dv_hdr10plus_combo(self) -> bool:
        mi = self.media_info
        has_hdr10plus = bool(
            getattr(mi, "has_hdrplus", False)
            or getattr(mi, "has_hdr10plus", False)
        )
        return bool(
            self.preserve_hdrplus
            and getattr(mi, "has_dv", False)
            and has_hdr10plus
        )


@dataclass(frozen=True)
class DVWorkFiles:
    root: Path
    src_hevc: Path
    p8_hevc: Path
    rpu_orig: Path
    rpu_final: Path
    rpu_verify: Path
    enc_hevc: Path
    hdr10plus_json: Path
    hdr10plus_hevc: Path
    hdr10plus_verify_json: Path
    injected: Path
    audio_mux_src: Path
    edit_json: Path
    level5_source_json: Path
    plain_mp4: Path

    @classmethod
    def create(cls, root: Path) -> "DVWorkFiles":
        return cls(
            root=root,
            src_hevc=root / "source.hevc",
            p8_hevc=root / "p8.hevc",
            rpu_orig=root / "metadata.rpu",
            rpu_final=root / "metadata_final.rpu",
            rpu_verify=root / "metadata_verify.rpu",
            enc_hevc=root / "encoded.hevc",
            hdr10plus_json=root / "metadata_hdr10plus.json",
            hdr10plus_hevc=root / "hdr10plus.hevc",
            hdr10plus_verify_json=root / "metadata_hdr10plus_verify.json",
            injected=root / "injected.hevc",
            audio_mux_src=root / "audio_tracks.mka",
            edit_json=root / "level5.json",
            level5_source_json=root / "level5_source.json",
            plain_mp4=root / "no_dv.mp4",
        )


@dataclass
class DVPipelineState:
    request: DVRunRequest
    files: DVWorkFiles
    audio_meta: list[dict] = field(default_factory=list)
    audio_tracks: list[DVExtractedAudioTrack] = field(default_factory=list)
    mux_audio_tracks: list[DVMuxAudioTrack] = field(default_factory=list)
    mux_subtitle_tracks: list[DVMuxSubtitleTrack] = field(default_factory=list)
    profile_hevc: Path | None = None
    rpu_to_use: Path | None = None
    rpu_input_hevc: Path | None = None
    sidecar_paths: list[str] = field(default_factory=list)
    verified_hdr10plus: bool = False
    verified_dolby_vision: bool = False
    effective_crop: str | None = None
    effective_vf_args: list = field(default_factory=list)


@dataclass(frozen=True)
class DVPipelineResult:
    success: bool
    sidecar_paths: tuple[str, ...] = ()
    failure_reason: str = ""
    failure_stage: str = ""
    verified_hdr10plus: bool = False
    verified_dolby_vision: bool = False
    effective_crop: str | None = None
    effective_vf_args: list = field(default_factory=list)
