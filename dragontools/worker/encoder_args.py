from __future__ import annotations

from ..core.codec_utils import normalize_target_codec, value_or_default
from ..core.type_utils import _safe_bool, _safe_int


def _int_option(options: dict, key: str, default: int = 0) -> int:
    value = _safe_int(value_or_default(options.get(key), default), default)
    return default if value is None else value


def _bounded_int_option(options: dict, key: str, default: int, minimum: int, maximum: int) -> int:
    value = _int_option(options, key, default)
    return max(minimum, min(maximum, value))


def _text_option(options: dict, key: str, allowed: set[str]) -> str | None:
    value = str(value_or_default(options.get(key), "auto") or "auto").strip().lower()
    if value in {"", "auto", "default"}:
        return None
    return value if value in allowed else None


def _h265_10bit_args(encoder_key: str) -> list[str]:
    pix_fmt = "yuv420p10le" if encoder_key == "cpu" else "p010le"
    args = ["-profile:v", "main10", "-pix_fmt", pix_fmt]
    if encoder_key == "amf":
        args += ["-bitdepth", "10"]
    return args


def _av1_10bit_args(encoder_key: str) -> list[str]:
    # FFmpeg-Softwareencoder erwarten planar 10-bit, Hardwarepfade P010.
    pix_fmt = "yuv420p10le" if encoder_key == "cpu" else "p010le"
    return ["-pix_fmt", pix_fmt]


_HDR10_X265_VUI_PARAMS = (
    "colorprim=bt2020",
    "transfer=smpte2084",
    "colormatrix=bt2020nc",
    "range=limited",
    "hdr10=1",
)


def _cpu_args(codec, crf, preset, encoder_options):
    em = {"h264": "libx264", "h265": "libx265", "av1": "libsvtav1"}
    if codec not in em:
        raise ValueError(f"CPU: nicht unterstützter Ziel-Codec: {codec!r}")
    args = ["-c:v", em[codec], "-crf", str(crf), "-preset", str(preset)]
    if codec == "h265":
        o = encoder_options
        p: list[str] = []
        for option_key, x265_key in (
            ("aq_mode", "aq-mode"),
            ("aq_strength", "aq-strength"),
            ("psy_rd", "psy-rd"),
            ("psy_rdoq", "psy-rdoq"),
        ):
            value = o.get(option_key)
            if value is not None:
                p.append(f"{x265_key}={value}")

        bf = _int_option(o, "bf", 0)
        if o.get("bf") is not None:
            p.append(f"bframes={bf}")
        lookahead = _int_option(o, "rc_lookahead", 0)
        if bf > 0 and lookahead > 0:
            p.append(f"rc-lookahead={lookahead}")
        if o.get("_force_hdr10_vui"):
            p.extend(_HDR10_X265_VUI_PARAMS)

        tune = str(value_or_default(o.get("tune"), "none") or "none").strip().lower()
        if tune != "none":
            args += ["-tune", tune]
        if p:
            args += ["-x265-params", ":".join(p)]
        args += _h265_10bit_args("cpu")
    elif codec == "av1" and encoder_options.get("_force_10bit"):
        args += _av1_10bit_args("cpu")
    return args


def _nvenc_args(codec, crf, encoder_options):
    em = {"h264": "h264_nvenc", "h265": "hevc_nvenc", "av1": "av1_nvenc"}
    if codec not in em:
        raise ValueError(f"NVENC: nicht unterstützter Ziel-Codec: {codec!r}")
    enc = em[codec]
    o = encoder_options
    cq_max = 63 if codec == "av1" else 51
    cq = _bounded_int_option(o, "cq", int(crf), 0, cq_max)
    args = [
        "-c:v", enc,
        "-preset", str(value_or_default(o.get("preset"), "p6")),
        "-rc", "vbr",
        "-cq", str(cq),
        "-b:v", "0",
    ]
    # Use the canonical FFmpeg/NVENC spellings.  Older FFmpeg releases
    # accepted underscore aliases as well, but current builds expose only the
    # hyphenated names for Spatial/Temporal AQ.  Keeping the canonical form
    # makes the same argument builder safe for Standard, DV, HDR10+ and
    # per-file override paths.
    if _safe_bool(value_or_default(o.get("spatial_aq"), True), True):
        args += [
            "-spatial-aq", "1",
            "-aq-strength", str(_bounded_int_option(o, "aq_strength", 8, 1, 15)),
        ]
    if _safe_bool(value_or_default(o.get("temporal_aq"), False), False):
        args += ["-temporal-aq", "1"]
    bf = _int_option(o, "bf", 0)
    lookahead = _int_option(o, "rc_lookahead", 32)
    if bf > 0 and lookahead > 0:
        args += ["-rc-lookahead", str(lookahead)]
        lookahead_level = _text_option(o, "lookahead_level", {str(i) for i in range(4)})
        if lookahead_level is not None:
            args += ["-lookahead_level", lookahead_level]
    if bf > 0:
        args += ["-bf", str(bf)]
    multipass = _text_option(o, "multipass", {"disabled", "qres", "fullres"})
    if multipass is not None:
        args += ["-multipass", multipass]
    bref = _text_option(o, "bref_mode", {"disabled", "each", "middle"}) or "disabled"
    if bf > 0 and bref != "disabled" and codec in ("h264", "h265"):
        args += ["-b_ref_mode", bref]
    if codec == "h265":
        args += _h265_10bit_args("nvenc")
    elif codec == "av1" and encoder_options.get("_force_10bit"):
        args += _av1_10bit_args("nvenc")
    return args


def _qsv_args(codec, crf, encoder_options):
    em = {"h264": "h264_qsv", "h265": "hevc_qsv", "av1": "av1_qsv"}
    if codec not in em:
        raise ValueError(f"QSV: nicht unterstützter Ziel-Codec: {codec!r}")
    o = encoder_options
    quality = _bounded_int_option(o, "q", int(crf), 1, 51)
    lookahead_depth = _bounded_int_option(o, "lookahead_depth", 40, 1, 100)
    args = [
        "-c:v", em[codec],
        "-preset", str(value_or_default(o.get("preset"), "medium")),
        # QSV quality modes are selected through global_quality.  Using -q
        # sets the generic QSCALE flag (CQP); combining that with look_ahead
        # is rejected by FFmpeg as two simultaneous RC modes.
        "-global_quality", str(quality),
    ]

    if codec == "h264":
        # h264_qsv exposes the classic look_ahead switch. Together with
        # global_quality this selects LA_ICQ instead of conflicting with CQP.
        args += [
            "-look_ahead", "1",
            "-look_ahead_depth", str(lookahead_depth),
        ]
    else:
        # Current hevc_qsv/av1_qsv no longer expose the h264-only
        # ``look_ahead`` AVOption. Their documented lookahead depth is tied to
        # ExtBRC, so use only options those encoders actually expose.
        args += [
            "-extbrc", "1",
            "-look_ahead_depth", str(lookahead_depth),
        ]

    if codec == "h265":
        args += _h265_10bit_args("qsv")
    elif codec == "av1" and encoder_options.get("_force_10bit"):
        args += _av1_10bit_args("qsv")
    return args


def _amf_args(codec, crf, encoder_options):
    em = {"h264": "h264_amf", "h265": "hevc_amf", "av1": "av1_amf"}
    if codec not in em:
        raise ValueError(f"AMF: nicht unterstützter Ziel-Codec: {codec!r}")
    o = encoder_options
    qp_max = 255 if codec == "av1" else 51
    qp = _bounded_int_option(o, "qp", int(crf), 0, qp_max)
    args = [
        "-c:v", em[codec],
        "-quality", str(value_or_default(o.get("quality"), "balanced")),
        "-qp_i", str(qp),
        "-qp_p", str(qp),
    ]
    # FFmpeg AMF exposes qp_b for H.264 and AV1, but not for HEVC.  Passing
    # -qp_b to hevc_amf therefore fails at option parsing on current builds.
    if codec in {"h264", "av1"}:
        args += ["-qp_b", str(qp)]
    if codec == "h265":
        args += _h265_10bit_args("amf")
    elif codec == "av1" and encoder_options.get("_force_10bit"):
        args += _av1_10bit_args("amf")
    return args


def _vid_args(codec, crf, preset, encoder_options):
    codec = normalize_target_codec(codec)
    e = str(value_or_default(encoder_options.get("encoder"), "cpu") or "cpu").strip().lower()
    builders = {
        "nvenc": _nvenc_args,
        "qsv": _qsv_args,
        "amf": _amf_args,
        "cpu": None,
    }
    if e not in builders:
        raise ValueError(
            f"Nicht unterstützter Encoder: {e!r}. Erlaubt: amf, cpu, nvenc, qsv."
        )
    if e == "cpu":
        return _cpu_args(codec, crf, preset, encoder_options)
    return builders[e](codec, crf, encoder_options)  # type: ignore[index]


def _scale(scale_mode):
    """Liefert einen reinen Downscale-Filter für die gewählte Zielhöhe.

    ``ih`` ist die Bildhöhe am Eingang des scale-Filters. Da AutoCrop vor
    scale ausgeführt wird, ist das automatisch die *aktive* Höhe nach Crop.
    ``min(target, ih)`` verhindert damit auch nach einem späteren DV/RPU-
    Crop-Abgleich zuverlässig jedes unbeabsichtigte Upscaling.

    Das Komma der FFmpeg-Expression muss innerhalb einer Filterkette escaped
    werden, weil es sonst als Trenner zum nächsten Filter interpretiert würde.
    """
    target_height = {
        "1080p": 1080,
        "720p": 720,
        "480p": 480,
        "4k": 2160,
    }.get(str(scale_mode or "").strip().lower())
    if target_height is None:
        return None
    return fr"scale=-2:min({target_height}\,ih)"
