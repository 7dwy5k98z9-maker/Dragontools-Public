from __future__ import annotations

from dataclasses import dataclass

from .media_metadata import normalize_video_codec
from .type_utils import _safe_bool


@dataclass(frozen=True, slots=True)
class SdrHdrEnhancementConfig:
    enabled: bool = False
    contrast_recovery: float = 0.30
    backend: str = "ffmpeg"

    @classmethod
    def from_encoder_options(cls, options: dict | None) -> "SdrHdrEnhancementConfig":
        data = dict(options or {})
        try:
            contrast = float(data.get("sdr_hdr_contrast_recovery", 0.30))
        except (TypeError, ValueError):
            contrast = 0.30
        backend = str(data.get("sdr_hdr_backend", "ffmpeg") or "ffmpeg").strip().lower()
        if backend not in {"ffmpeg", "davinci_free", "comfyui"}:
            backend = "ffmpeg"
        return cls(
            enabled=_safe_bool(data.get("sdr_hdr_enabled", False), False),
            contrast_recovery=max(0.0, min(3.0, contrast)),
            backend=backend,
        )


@dataclass(frozen=True, slots=True)
class SdrHdrEnhancementDecision:
    requested: bool
    applied: bool
    reason: str
    filter_chain: tuple[str, ...] = ()


def _norm(value: object) -> str:
    return str(value or "").strip().lower().replace("_", "-").replace(" ", "")


def _resolve_matrix_label(media_info, video) -> str:
    """Return a matrix-coefficients label, never a generic pixel-family label.

    MediaInfo exposes both ``ColorSpace`` (often just ``YUV``) and the actual
    ``matrix_coefficients`` (for example ``BT.709``).  The latter must win;
    treating generic YUV/RGB as a matrix would reject otherwise valid SDR
    sources.
    """
    explicit = _norm(getattr(media_info, "matrix_coefficients", None))
    if explicit:
        return explicit

    fallback = _norm(getattr(video, "color_space", None))
    if fallback in {"", "yuv", "rgb", "gbr", "xyz"}:
        return ""
    return fallback


def source_is_supported_sdr_bt709(media_info) -> tuple[bool, str]:
    if media_info is None:
        return False, "Medienanalyse fehlt."
    if bool(getattr(media_info, "is_hdr", False)) or bool(getattr(media_info, "has_dv", False)):
        return False, "Quelle ist bereits HDR/Dolby Vision."
    if bool(getattr(media_info, "has_hdrplus", False)) or bool(getattr(media_info, "has_hdr10plus", False)):
        return False, "Quelle enthält bereits HDR10+."

    video = getattr(media_info, "primary_video", None)
    if video is None:
        return False, "Kein primärer Videostream vorhanden."

    primaries = _norm(getattr(video, "color_primaries", None))
    transfer = _norm(
        getattr(video, "color_transfer", None)
        or getattr(media_info, "transfer_characteristics", None)
    )
    matrix = _resolve_matrix_label(media_info, video)

    if primaries not in {"bt709", "bt.709"}:
        return False, f"BT.709-Primärfarben nicht eindeutig ({primaries or 'unbekannt'})."
    if transfer not in {"bt709", "bt.709"}:
        return False, f"BT.709-Transfer nicht eindeutig ({transfer or 'unbekannt'})."
    if matrix and matrix not in {"bt709", "bt.709"}:
        return False, f"BT.709-Matrix nicht eindeutig ({matrix})."
    return True, "SDR BT.709 eindeutig erkannt."


def build_sdr_to_hdr_filters(config: SdrHdrEnhancementConfig) -> tuple[str, ...]:
    contrast = f"{config.contrast_recovery:.2f}"
    inverse = (
        "libplacebo=format=p010le"
        ":colorspace=bt2020nc"
        ":color_primaries=bt2020"
        ":color_trc=smpte2084"
        ":range=tv"
        ":inverse_tonemapping=1"
        ":tonemapping=spline"
        ":gamut_mode=perceptual"
        f":contrast_recovery={contrast}"
    )
    setparams = (
        "setparams=range=limited"
        ":colorspace=bt2020nc"
        ":color_primaries=bt2020"
        ":color_trc=smpte2084"
    )
    return inverse, setparams


def decide_sdr_hdr_enhancement(
    media_info,
    *,
    target_codec: str,
    encoder_options: dict | None,
) -> SdrHdrEnhancementDecision:
    config = SdrHdrEnhancementConfig.from_encoder_options(encoder_options)
    if not config.enabled:
        return SdrHdrEnhancementDecision(False, False, "deaktiviert")

    codec = normalize_video_codec(target_codec)
    if codec not in {"hevc", "av1"}:
        return SdrHdrEnhancementDecision(True, False, "SDR→HDR wird nur für H.265/HEVC und AV1 angeboten.")

    supported, reason = source_is_supported_sdr_bt709(media_info)
    if not supported:
        return SdrHdrEnhancementDecision(True, False, reason)

    if config.backend == "davinci_free":
        available = _safe_bool((encoder_options or {}).get("_davinci_resolve_available", False), False)
        if not available:
            return SdrHdrEnhancementDecision(
                True, False,
                "DaVinci Resolve wurde als SDR→HDR-Backend gewählt, ist aber nicht verfügbar.",
            )
        return SdrHdrEnhancementDecision(
            True, False,
            "DaVinci Resolve Free ist als Backend vorbereitet, aber nicht automatisch ausführbar: "
            "die externe Remote-/Developer-Scripting-Steuerung wird nicht für Resolve Free vorausgesetzt.",
        )

    if config.backend == "comfyui":
        data = encoder_options or {}
        if not _safe_bool(data.get("_comfyui_api_available", False), False):
            return SdrHdrEnhancementDecision(
                True, False,
                "ComfyUI wurde als SDR→HDR-Backend gewählt, aber die lokale API ist nicht erreichbar.",
            )
        if not _safe_bool(data.get("_comfyui_model_assets_ready", False), False):
            return SdrHdrEnhancementDecision(
                True, False,
                str(data.get("_comfyui_model_error") or "HDRTVDM-Modell/Checkpoint ist noch nicht eingerichtet."),
            )
        if not _safe_bool(data.get("_comfyui_required_nodes_available", False), False):
            return SdrHdrEnhancementDecision(
                True, False,
                "ComfyUI ist erreichbar, aber die DragonTools-HDRTVDM-Custom-Nodes fehlen.",
            )
        if not _safe_bool(data.get("_comfyui_workflow_valid", False), False):
            return SdrHdrEnhancementDecision(
                True, False,
                "ComfyUI ist erreichbar, aber der API-Workflow ist ungültig.",
            )
        video = getattr(media_info, "primary_video", None)
        frame_rate_mode = str(getattr(video, "frame_rate_mode", "") or "").strip().upper()
        if frame_rate_mode != "CFR":
            return SdrHdrEnhancementDecision(
                True, False,
                "ComfyUI/HDRTVDM unterstützt aktuell nur eindeutig erkannte CFR-Quellen; "
                f"Framerate-Modus ist {frame_rate_mode or 'unbekannt'}.",
            )
        if not str(getattr(video, "frame_rate", "") or "").strip():
            return SdrHdrEnhancementDecision(
                True, False,
                "ComfyUI/HDRTVDM benötigt eine bekannte Quellframerate.",
            )
        return SdrHdrEnhancementDecision(
            True, True,
            "SDR BT.709 wird über ComfyUI/HDRTVDM als vollständige Datei nach BT.2020/PQ konvertiert.",
        )

    if not _safe_bool((encoder_options or {}).get("_sdr_hdr_libplacebo_available", False), False):
        return SdrHdrEnhancementDecision(True, False, "FFmpeg/libplacebo ist nicht verfügbar.")
    return SdrHdrEnhancementDecision(
        True,
        True,
        "SDR BT.709 wird per FFmpeg/libplacebo Range Expansion nach BT.2020/PQ erweitert.",
        build_sdr_to_hdr_filters(config),
    )
