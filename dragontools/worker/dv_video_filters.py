from __future__ import annotations


_DV_SETPARAMS = (
    "setparams=range=limited"
    ":colorspace=bt2020nc"
    ":color_primaries=bt2020"
    ":color_trc=smpte2084"
)

_DV_VF_PREFIX = f"format=p010le,{_DV_SETPARAMS},"
_DV_VF_SUFFIX = f",format=p010le,{_DV_SETPARAMS}"

_DV_P5_ICTCP_TO_BT2020 = (
    "zscale="
    "matrixin=ictcp:transferin=smpte2084:primariesin=bt2020:rangein=full"
    ":matrix=bt2020nc:transfer=smpte2084:primaries=bt2020:range=tv"
)

_DV_P5_LIBPLACEBO_FILTER = (
    "libplacebo=format=p010le"
    ":colorspace=bt2020nc"
    ":color_primaries=bt2020"
    ":color_trc=smpte2084"
    ":range=tv"
)


def build_dv5_libplacebo_vf(vf_args: list) -> list:
    """Build ffmpeg filter args for DV Profile 5 base-layer conversion."""
    cleaned: list = []
    i = 0
    while i < len(vf_args):
        if vf_args[i] == "-map" and i + 1 < len(vf_args):
            if str(vf_args[i + 1]) in ("0:v", "0:v:0", "1:v", "1:v:0"):
                i += 2
                continue
        cleaned.append(vf_args[i])
        i += 1

    if "-filter_complex" in cleaned:
        fc_idx = cleaned.index("-filter_complex")
        chain = cleaned[fc_idx + 1]
        if "[0:v:0]" in chain:
            chain = chain.replace("[0:v:0]", f"[0:v:0]{_DV_P5_LIBPLACEBO_FILTER},", 1)
        else:
            chain = f"{_DV_P5_LIBPLACEBO_FILTER},{chain}"
        cleaned[fc_idx + 1] = chain
        return cleaned

    try:
        vf_idx = cleaned.index("-vf")
        old_chain = cleaned[vf_idx + 1]
        cleaned[vf_idx + 1] = f"{_DV_P5_LIBPLACEBO_FILTER},{old_chain}"
    except (ValueError, IndexError):
        cleaned += ["-vf", _DV_P5_LIBPLACEBO_FILTER]

    return cleaned


def inject_dv_colorspace(vf_args: list, is_p5: bool = False) -> list:
    """Inject stable DV color metadata and p010 handoff into ffmpeg filter args."""
    result = list(vf_args)
    vf_prefix = (
        f"format=p010le,{_DV_P5_ICTCP_TO_BT2020},{_DV_SETPARAMS},"
        if is_p5
        else _DV_VF_PREFIX
    )

    if "-filter_complex" in result:
        fc_idx = result.index("-filter_complex")
        old_chain = result[fc_idx + 1]

        if "[1:v:0]" in old_chain:
            tail = old_chain[old_chain.index("[1:v:0]") + len("[1:v:0]") :]
            if tail.startswith("["):
                old_chain = old_chain.replace(
                    "[1:v:0]",
                    f"[1:v:0]{vf_prefix.rstrip(',')}[_dvfmt];[_dvfmt]",
                )
            else:
                old_chain = old_chain.replace("[1:v:0]", f"[1:v:0]{vf_prefix}")
        if "[vout]" in old_chain:
            old_chain = old_chain.replace("[vout]", f"{_DV_VF_SUFFIX}[vout]")
        else:
            old_chain += _DV_VF_SUFFIX

        result[fc_idx + 1] = old_chain
        return result

    try:
        vf_idx = result.index("-vf")
        old_chain = result[vf_idx + 1]
        result[vf_idx + 1] = vf_prefix + old_chain + _DV_VF_SUFFIX
    except (ValueError, IndexError):
        result += ["-vf", f"format=p010le,{_DV_SETPARAMS}"]

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
