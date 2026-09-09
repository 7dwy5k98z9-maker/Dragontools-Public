from __future__ import annotations

import re
from fractions import Fraction


def normalize_color_range_for_zscale(raw: str | None) -> str:
    """Konvertiert MediaInfo/ffprobe Farbraum-Range zu zscale-Format.

    MediaInfo: 'Full' oder 'Limited'
    ffprobe:   'pc' (full) oder 'tv' (limited)
    zscale:    'full' oder 'tv'

    Default ist 'tv' (limited) - sicherer Fallback für DV-Content.
    DV P5 HEVC-Streams sind VUI-seitig immer limited-range kodiert.
    """
    r = (raw or "").strip().lower()
    if r in ("full", "pc", "full range", "jpeg"):
        return "full"
    return "tv"


def normalize_color_range_label(raw: str | None) -> str:
    """Lesbarer Label für die Range (für Log/UI): 'Full' oder 'Limited'."""
    return "Full" if normalize_color_range_for_zscale(raw) == "full" else "Limited"


GERMAN_KEYS = ("de", "ger", "deu", "german", "deutsch")


def is_german(language: str | None, title: str | None = "") -> bool:
    language = (language or "").strip().lower()
    title = (title or "").strip().lower()
    if language:
        if language in GERMAN_KEYS:
            return True
        for sep in ("-", "_", "."):
            if language.startswith(f"de{sep}"):
                return True
    if title:
        title_tokens = {tok for tok in re.split(r"[^a-z0-9]+", title) if tok}
        if {"german", "deutsch", "deu", "ger"} & title_tokens:
            return True
    return False


def _normalize_lang(lang: str | None, title: str | None = "") -> str:
    if is_german(lang, title):
        return "de"
    return (lang or "und").lower()


def normalize_video_codec(codec: str | None) -> str:
    """Normalisiert Codec-Namen auf kanonische Kurzform ('h264', 'hevc', 'av1', ...)."""
    c = (codec or "").lower().strip()
    if c in {"h264", "avc", "avc1", "x264"}:
        return "h264"
    if c in {"h265", "hevc", "hvc1", "hev1", "x265"}:
        return "hevc"
    if c in {"av1", "av01"}:
        return "av1"
    return c


def _track_value(track: dict, *keys: str) -> object | None:
    for key in keys:
        if key in track and track.get(key) not in (None, ""):
            return track.get(key)
    return None


def _parse_mediainfo_bit_depth(track: dict) -> int | None:
    value = _track_value(track, "BitDepth", "Bit_depth")
    if value is None:
        return None
    match = re.search(r"(\d+)", str(value))
    if not match:
        return None
    try:
        bit_depth = int(match.group(1))
    except (TypeError, ValueError):
        return None
    return bit_depth if bit_depth > 0 else None


_COMMON_FRAME_RATES = (
    (24000, 1001),
    (24, 1),
    (25, 1),
    (30000, 1001),
    (30, 1),
    (50, 1),
    (60000, 1001),
    (60, 1),
)


def _parse_seconds_value(value: object | None) -> float | None:
    if value in (None, "", "N/A"):
        return None
    try:
        seconds = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None


def _parse_mediainfo_duration_s(value: object | None) -> float | None:
    seconds = _parse_seconds_value(value)
    if seconds is None:
        return None
    # MediaInfo JSON liefert Duration meistens in Millisekunden.
    return seconds / 1000.0 if seconds > 10000 else seconds


def _parse_frame_rate_fraction(value: object | None) -> Fraction | None:
    if value in (None, "", "N/A", "0/0"):
        return None
    text = str(value).strip().replace(",", ".")
    try:
        if "/" in text:
            num, den = text.split("/", 1)
            fps = Fraction(int(num), int(den))
        else:
            fps = Fraction(text).limit_denominator(1001)
        if fps <= 0:
            return None
        return _nearest_common_frame_rate(float(fps)) or fps
    except Exception:
        return None


def _nearest_common_frame_rate(value: float) -> Fraction | None:
    for num, den in _COMMON_FRAME_RATES:
        rate = Fraction(num, den)
        if abs(float(rate) - value) <= 0.001:
            return rate
    return None


def _frame_rate_label(*values: object | None) -> str | None:
    for value in values:
        fps = _parse_frame_rate_fraction(value)
        if fps is not None:
            return f"{fps.numerator}/{fps.denominator}"
    return None


def _frame_rate_mode_label(*values: object | None) -> str | None:
    for value in values:
        raw = str(value or "").strip()
        if not raw:
            continue
        low = raw.lower()
        if "constant" in low or low == "cfr":
            return "CFR"
        if "variable" in low or low == "vfr":
            return "VFR"
        return raw
    return None


def build_pix_fmt_from_mediainfo(track: dict) -> str | None:
    """
    Baut ein ffmpeg-kompatibles pix_fmt aus MediaInfo JSON-Feldern.

    Genutzt werden nur Speicherformat-Felder: ColorSpace, ChromaSubsampling und
    BitDepth. Farbwiedergabe-Metadaten wie transfer_characteristics,
    colour_primaries, matrix_coefficients oder colour_range bleiben getrennt.
    """
    try:
        color_space = str(_track_value(track, "ColorSpace") or "").strip().lower()
        chroma = str(
            _track_value(track, "ChromaSubsampling", "Chroma subsampling") or ""
        ).strip()
        bit_depth = _parse_mediainfo_bit_depth(track)

        if color_space != "yuv" or bit_depth is None:
            return None

        chroma_match = re.search(r"4\s*:\s*([024])\s*:\s*([024])", chroma)
        if not chroma_match:
            return None

        chroma_token = f"4{chroma_match.group(1)}{chroma_match.group(2)}"
        if chroma_token not in {"420", "422", "444"}:
            return None

        if bit_depth == 8:
            return f"yuv{chroma_token}p"
        if bit_depth > 8:
            return f"yuv{chroma_token}p{bit_depth}le"
    except Exception:
        return None
    return None


def parse_bit_depth(mi_track: dict, fp_stream: dict) -> int | None:
    """Ermittelt Bit-Tiefe: MediaInfo -> ffprobe bits_per_raw_sample -> pix_fmt-Ableitung."""
    mi_bit_depth = _parse_mediainfo_bit_depth(mi_track)
    if mi_bit_depth is not None:
        return mi_bit_depth
    bprs = fp_stream.get("bits_per_raw_sample")
    if bprs:
        try:
            bd = int(bprs)
            if bd > 0:
                return bd
        except Exception:
            pass
    pf = (fp_stream.get("pix_fmt") or "").lower()
    if "p12" in pf or "12le" in pf or "12be" in pf:
        return 12
    if "p10" in pf or "10le" in pf or "10be" in pf:
        return 10
    if pf in {"yuv420p", "yuvj420p", "yuv422p", "yuv444p", "nv12", "nv21", "rgb24", "bgr24"}:
        return 8
    return None
