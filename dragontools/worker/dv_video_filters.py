from __future__ import annotations


from .dv_filter_graph import prepend_video_filter, append_video_filter

_DV_SETPARAMS = (
    "setparams=range=limited"
    ":colorspace=bt2020nc"
    ":color_primaries=bt2020"
    ":color_trc=smpte2084"
)

_DV_P5_ICTCP_TO_BT2020 = (
    "zscale="
    "matrixin=ictcp:transferin=smpte2084:primariesin=bt2020:rangein=full"
    ":matrix=bt2020nc:transfer=smpte2084:primaries=bt2020:range=tv"
)

def _dv_vf_prefix(pixel_format: str) -> str:
    return f"format={pixel_format},{_DV_SETPARAMS},"


def _dv_vf_suffix(pixel_format: str) -> str:
    return f",format={pixel_format},{_DV_SETPARAMS}"


def _dv_p5_libplacebo_filter(pixel_format: str) -> str:
    return (
        f"libplacebo=format={pixel_format}"
        ":colorspace=bt2020nc"
        ":color_primaries=bt2020"
        ":color_trc=smpte2084"
        ":range=tv"
    )


def build_dv5_libplacebo_vf(vf_args: list, *, pixel_format: str = "p010le", source_stream_index: int | None = None) -> list:
    """Build ffmpeg filter args for DV Profile 5 base-layer conversion."""
    cleaned: list = []
    i = 0
    while i < len(vf_args):
        # A complex graph maps its filtered output. A simple -vf still
        # needs the explicit source mapping to prevent automatic selection.
        if "-filter_complex" in vf_args and vf_args[i] == "-map" and i + 1 < len(vf_args):
            if str(vf_args[i + 1]) in ("0:v", "0:v:0", "1:v", "1:v:0"):
                i += 2
                continue
        cleaned.append(vf_args[i])
        i += 1

    if "-filter_complex" in cleaned:
        fc_idx = cleaned.index("-filter_complex")
        chain = cleaned[fc_idx + 1]
        chain = prepend_video_filter(str(chain), _dv_p5_libplacebo_filter(pixel_format), source_stream_index=source_stream_index)
        cleaned[fc_idx + 1] = chain
        return cleaned

    if "-map" not in cleaned:
        cleaned += ["-map", "0:v:0"]
    try:
        vf_idx = cleaned.index("-vf")
        old_chain = cleaned[vf_idx + 1]
        cleaned[vf_idx + 1] = f"{_dv_p5_libplacebo_filter(pixel_format)},{old_chain}"
    except (ValueError, IndexError):
        cleaned += ["-vf", _dv_p5_libplacebo_filter(pixel_format)]

    return cleaned


def inject_dv_colorspace(
    vf_args: list,
    is_p5: bool = False,
    *,
    pixel_format: str = "p010le",
    source_stream_index: int | None = None,
) -> list:
    """Inject stable DV color metadata using the encoder-native 10-bit format."""
    result = list(vf_args)
    vf_prefix = (
        f"format={pixel_format},{_DV_P5_ICTCP_TO_BT2020},{_DV_SETPARAMS},"
        if is_p5
        else _dv_vf_prefix(pixel_format)
    )
    vf_suffix = _dv_vf_suffix(pixel_format)

    if "-filter_complex" in result:
        fc_idx = result.index("-filter_complex")
        old_chain = result[fc_idx + 1]

        old_chain = prepend_video_filter(str(old_chain), vf_prefix.rstrip(","), source_stream_index=source_stream_index)
        old_chain = append_video_filter(old_chain, result, vf_suffix.lstrip(","))

        result[fc_idx + 1] = old_chain
        return result

    try:
        vf_idx = result.index("-vf")
        old_chain = result[vf_idx + 1]
        result[vf_idx + 1] = vf_prefix + old_chain + vf_suffix
    except (ValueError, IndexError):
        result += ["-vf", f"format={pixel_format},{_DV_SETPARAMS}"]

    return result


def remap_vf_to_input1(vf_args: list) -> list:
    """Move video filter references from the source input to the encoded input."""
    result = []
    i = 0

    while i < len(vf_args):
        arg = vf_args[i]

        if arg == "-map" and i + 1 < len(vf_args):
            target = str(vf_args[i + 1])
            if target in ("0:v", "0:v:0", "1:v", "1:v:0"):
                i += 2
                continue

        if isinstance(arg, str) and "[0:v:0]" in arg:
            arg = arg.replace("[0:v:0]", "[1:v:0]")

        result.append(arg)
        i += 1

    return result
