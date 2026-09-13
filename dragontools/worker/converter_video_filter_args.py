from __future__ import annotations


def base_vf_args(pre_filters: list[str], post_filters: list[str] | None = None) -> list:
    filters = list(pre_filters) + list(post_filters or [])
    return ["-map", "0:v:0"] + (["-vf", ",".join(filters)] if filters else [])


def image_burn_vf_args(mi, burn_sub, pre_filters: list[str], post_filters: list[str] | None = None) -> list:
    ordinal = next((i for i, stream in enumerate(mi.subtitle_streams) if stream.index == burn_sub.index), 0)
    post = ",".join(post_filters or [])
    if pre_filters and post:
        graph = f"[0:v:0]{','.join(pre_filters)}[vpre];[vpre][0:s:{ordinal}]overlay[vburn];[vburn]{post}[vout]"
    elif pre_filters:
        graph = f"[0:v:0]{','.join(pre_filters)}[vpre];[vpre][0:s:{ordinal}]overlay[vout]"
    elif post:
        graph = f"[0:v:0][0:s:{ordinal}]overlay[vburn];[vburn]{post}[vout]"
    else:
        graph = f"[0:v:0][0:s:{ordinal}]overlay[vout]"
    return ["-filter_complex", graph, "-map", "[vout]"]
