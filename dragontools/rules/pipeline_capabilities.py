from __future__ import annotations

from ..core.media_metadata import normalize_video_codec
from ..core.models import MediaInfo, Pipeline, TargetCodec
from .pipeline_policy import PipelinePolicyState


def classify_source_codec(media_info: MediaInfo) -> str:
    primary_video = media_info.primary_video
    if primary_video is None:
        return ""
    return normalize_video_codec(primary_video.codec)


def source_dynamic_hdr_flags(media_info: MediaInfo) -> tuple[bool, bool]:
    has_dv = bool(getattr(media_info, "has_dv", False))
    has_hdrplus = bool(
        getattr(media_info, "has_hdrplus", False)
        or getattr(media_info, "has_hdr10plus", False)
    )
    return has_dv, has_hdrplus


def pipeline_capability_error(
    pipeline: Pipeline,
    *,
    source_codec: str,
    target_codec: str,
    media_info: MediaInfo,
) -> str | None:
    """Return the reason an explicitly selected pipeline cannot execute."""
    if pipeline == Pipeline.STANDARD:
        return None
    if pipeline == Pipeline.DV:
        if target_codec != TargetCodec.H265.value:
            return "HEVC-Dolby Vision-Pipeline benötigt Zielcodec H.265."
        if source_codec != "hevc":
            return "HEVC-Dolby-Vision kann nur aus einer HEVC/H.265-Quelle erhalten werden."
        if not media_info.has_dv:
            return "Dolby-Vision-Pipeline angefordert, aber die Quelle enthält kein Dolby Vision."
        return None
    if pipeline == Pipeline.HDRPLUS:
        if target_codec != TargetCodec.H265.value:
            return "HEVC-HDR10+-Pipeline benötigt Zielcodec H.265."
        if source_codec != "hevc":
            return "HEVC-HDR10+-Pipeline benötigt eine HEVC/H.265-Quelle."
        if not media_info.has_hdrplus:
            return "HDR10+-Pipeline angefordert, aber die Quelle enthält kein HDR10+."
        return None
    if pipeline == Pipeline.AV1_DV:
        if target_codec != TargetCodec.AV1.value:
            return "AV1-Dolby-Vision-Pipeline benötigt Zielcodec AV1."
        if source_codec not in {"hevc", "av1"}:
            return "AV1-Dolby-Vision unterstützt derzeit HEVC- oder AV1-DV-Quellen."
        if not media_info.has_dv:
            return "AV1-Dolby-Vision-Pipeline angefordert, aber die Quelle enthält kein Dolby Vision."
        return None
    if pipeline == Pipeline.AV1_HDRPLUS:
        if target_codec != TargetCodec.AV1.value:
            return "AV1-HDR10+-Pipeline benötigt Zielcodec AV1."
        if source_codec not in {"hevc", "av1"}:
            return "AV1-HDR10+ unterstützt derzeit HEVC- oder AV1-HDR10+-Quellen."
        if not (
            getattr(media_info, "has_hdrplus", False)
            or getattr(media_info, "has_hdr10plus", False)
        ):
            return "AV1-HDR10+-Pipeline angefordert, aber die Quelle enthält kein HDR10+."
        return None
    return f"Unbekannte Pipeline: {pipeline!r}"


def apply_dynamic_hdr_capability_guards(
    state: PipelinePolicyState,
    *,
    source_codec: str,
    target_codec: str,
    source_has_dv: bool,
    source_has_hdrplus: bool,
    requested_dv: bool,
    requested_hdrplus: bool,
) -> None:
    """Disable preservation contracts that the source/target combination cannot satisfy."""
    if source_has_dv and state.effective_dv:
        _guard_one_dynamic_hdr(
            state,
            flag="dv",
            label="Dolby Vision",
            source_codec=source_codec,
            target_codec=target_codec,
            requested=bool(requested_dv),
        )

    if source_has_hdrplus and state.effective_hdrplus:
        _guard_one_dynamic_hdr(
            state,
            flag="hdr10plus",
            label="HDR10+",
            source_codec=source_codec,
            target_codec=target_codec,
            requested=bool(requested_hdrplus),
        )


def _guard_one_dynamic_hdr(
    state: PipelinePolicyState,
    *,
    flag: str,
    label: str,
    source_codec: str,
    target_codec: str,
    requested: bool,
) -> None:
    source_label = source_codec.upper() or "Unbekannte"
    if target_codec == TargetCodec.H265.value and source_codec != "hevc":
        state.disable(
            flag,
            f"{source_label}-Quelle: {label} kann im HEVC-Pfad nicht erhalten werden",
            archive=True,
        )
    elif target_codec == TargetCodec.AV1.value and source_codec not in {"hevc", "av1"}:
        av1_label = "Dolby-Vision" if flag == "dv" else label
        state.disable(
            flag,
            f"{source_label}-Quelle: AV1-{av1_label} unterstützt derzeit nur HEVC/AV1 als Quelle",
            archive=True,
        )
    elif target_codec not in {TargetCodec.H265.value, TargetCodec.AV1.value}:
        state.disable(
            flag,
            f"Zielcodec {target_codec.upper()}: {label} kann nur mit H.265 oder AV1 erhalten werden",
            archive=requested,
        )
