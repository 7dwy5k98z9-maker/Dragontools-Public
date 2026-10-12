"""Subtitle format registry used by the standalone subtitle tab.

The GUI must not silently drop subtitle streams merely because a codec was not
added to a small extension table.  Known codecs get a convenient native/text
sidecar where possible; every codec also gets a lossless Matroska subtitle-only
fallback (``.mks``).  For codecs that FFmpeg can decode as text but that are not
known yet, an SRT conversion is attempted after the lossless fallback.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SubtitleExtractionTarget:
    suffix: str
    codec_args: tuple[str, ...]
    description: str


# Extensions accepted for explicit/automatic subtitle sidecars.  The explicit
# file dialog additionally offers "All files" and validation is performed via
# ffprobe/mkvmerge, so this set is deliberately broad but subtitle-specific.
SUBTITLE_SIDECAR_EXTENSIONS = frozenset({
    ".srt", ".ass", ".ssa", ".vtt", ".webvtt", ".sup", ".pgs",
    ".mks", ".idx", ".sub", ".ttml", ".dfxp", ".smi", ".sami",
    ".jss", ".stl", ".scc", ".sbv", ".mpl", ".mpl2", ".usf",
    ".lrc", ".rt", ".pjs", ".aqt", ".vplayer",
})

SUBTITLE_FILE_DIALOG_FILTER = (
    "Untertitel ("
    + " ".join(f"*{suffix}" for suffix in sorted(SUBTITLE_SIDECAR_EXTENSIONS))
    + ");;Alle Dateien (*)"
)


# Codecs that can sensibly be converted to MP4/MOV mov_text.  ASS/SSA styling
# cannot survive mov_text, but this preserves the established DragonTools
# behaviour for MP4/MOV while allowing the caller to fall back to MKV when the
# subtitle is bitmap/binary or otherwise unknown.
TEXT_SUBTITLE_CODECS = frozenset({
    "subrip", "srt", "ass", "ssa", "webvtt", "wvtt", "mov_text",
    "subt", "tx3g", "text", "ttml", "dfxp", "sami", "subviewer",
    "subviewer1", "microdvd", "jacosub", "mpl2", "realtext", "vplayer",
    "pjs", "aqtitle", "eia_608", "eia608", "cc_dec", "lrc",
})

BITMAP_SUBTITLE_CODECS = frozenset({
    "hdmv_pgs_subtitle", "pgssub", "dvd_subtitle", "dvb_subtitle", "xsub",
    "dvb_teletext", "arib_caption",
})


# Preferred human-usable extraction.  A .mks copy fallback is added below to
# every entry, so a failed conversion does not discard the stream.
_PREFERRED_EXTRACTION: dict[str, SubtitleExtractionTarget] = {
    "subrip": SubtitleExtractionTarget(".srt", ("-c:s", "srt"), "SubRip/SRT"),
    "srt": SubtitleExtractionTarget(".srt", ("-c:s", "srt"), "SubRip/SRT"),
    "ass": SubtitleExtractionTarget(".ass", ("-c:s", "ass"), "ASS"),
    "ssa": SubtitleExtractionTarget(".ass", ("-c:s", "ass"), "ASS"),
    "webvtt": SubtitleExtractionTarget(".vtt", ("-c:s", "webvtt"), "WebVTT"),
    "wvtt": SubtitleExtractionTarget(".vtt", ("-c:s", "webvtt"), "WebVTT"),
    "mov_text": SubtitleExtractionTarget(".srt", ("-c:s", "srt"), "SRT"),
    "subt": SubtitleExtractionTarget(".srt", ("-c:s", "srt"), "SRT"),
    "tx3g": SubtitleExtractionTarget(".srt", ("-c:s", "srt"), "SRT"),
    "text": SubtitleExtractionTarget(".srt", ("-c:s", "srt"), "SRT"),
    "ttml": SubtitleExtractionTarget(".ttml", ("-c:s", "ttml"), "TTML"),
    "dfxp": SubtitleExtractionTarget(".ttml", ("-c:s", "ttml"), "TTML"),
    "hdmv_pgs_subtitle": SubtitleExtractionTarget(".sup", ("-c:s", "copy"), "PGS/SUP"),
    "pgssub": SubtitleExtractionTarget(".sup", ("-c:s", "copy"), "PGS/SUP"),
    # Formats without a reliable standalone one-file representation are kept
    # losslessly in Matroska subtitle-only sidecars.
    "dvd_subtitle": SubtitleExtractionTarget(".mks", ("-c:s", "copy", "-f", "matroska"), "Matroska/VobSub"),
    "dvb_subtitle": SubtitleExtractionTarget(".mks", ("-c:s", "copy", "-f", "matroska"), "Matroska/DVB"),
    "xsub": SubtitleExtractionTarget(".mks", ("-c:s", "copy", "-f", "matroska"), "Matroska/XSUB"),
    "dvb_teletext": SubtitleExtractionTarget(".mks", ("-c:s", "copy", "-f", "matroska"), "Matroska/Teletext"),
    "arib_caption": SubtitleExtractionTarget(".mks", ("-c:s", "copy", "-f", "matroska"), "Matroska/ARIB"),
}

_MKS_FALLBACK = SubtitleExtractionTarget(
    ".mks", ("-c:s", "copy", "-f", "matroska"), "verlustfreier Matroska-Fallback"
)
_SRT_FALLBACK = SubtitleExtractionTarget(
    ".srt", ("-c:s", "srt"), "SRT-Konvertierungsfallback"
)


def normalize_subtitle_codec(codec: str | None, codec_tag: str | None = None) -> str:
    """Normalize ffprobe codec names/tags, including the MP4 ``wvtt`` tag."""
    name = (codec or "").strip().casefold()
    tag = (codec_tag or "").strip().casefold()
    if name in {"", "unknown", "none"} and tag:
        return tag
    if tag == "wvtt" and name in {"webvtt", "unknown", ""}:
        return "webvtt"
    return name or tag or "unknown"


def subtitle_extraction_targets(
    codec: str | None, codec_tag: str | None = None
) -> tuple[SubtitleExtractionTarget, ...]:
    """Return ordered extraction attempts for *every* subtitle codec.

    Unknown codecs are not rejected.  They are first copied into an ``.mks``
    sidecar; if that container cannot represent the codec, FFmpeg is given one
    final chance to decode it to SRT.
    """
    normalized = normalize_subtitle_codec(codec, codec_tag)
    preferred = _PREFERRED_EXTRACTION.get(normalized)
    targets: list[SubtitleExtractionTarget] = []
    if preferred is not None:
        targets.append(preferred)
    if preferred != _MKS_FALLBACK:
        targets.append(_MKS_FALLBACK)
    if preferred is None and normalized not in BITMAP_SUBTITLE_CODECS:
        targets.append(_SRT_FALLBACK)

    # Stable de-duplication by actual output strategy.
    unique: list[SubtitleExtractionTarget] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for target in targets:
        key = (target.suffix, target.codec_args)
        if key not in seen:
            seen.add(key)
            unique.append(target)
    return tuple(unique)


def subtitle_codec_is_text(codec: str | None, codec_tag: str | None = None) -> bool:
    return normalize_subtitle_codec(codec, codec_tag) in TEXT_SUBTITLE_CODECS
