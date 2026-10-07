from __future__ import annotations


def base_vf_args(pre_filters: list[str], post_filters: list[str] | None = None) -> list:
    filters = list(pre_filters) + list(post_filters or [])
    return ["-map", "0:v:0"] + (["-vf", ",".join(filters)] if filters else [])


def image_burn_vf_args(mi, burn_sub, pre_filters: list[str], post_filters: list[str] | None = None) -> list:
    ordinal = next(
        (i for i, stream in enumerate(mi.subtitle_streams) if stream.index == burn_sub.index),
        None,
    )
    if ordinal is None:
        raise ValueError(
            f"Geplanter Bild-Untertitelstream #{burn_sub.index} ist in der aktuellen Medienanalyse nicht vorhanden."
        )
    # Bitmap subtitles (PGS/VobSub) are rendered in the source video canvas.
    # Cropping/scaling the main video *before* overlay leaves the subtitle
    # bitmap in the old coordinate system and can shift or clip it. Overlay in
    # source coordinates first, then apply all video transforms to the combined
    # image so subtitle placement remains geometrically stable.
    filters = list(pre_filters) + list(post_filters or [])
    if filters:
        graph = f"[0:v:0][0:s:{ordinal}]overlay[vburn];[vburn]{','.join(filters)}[vout]"
    else:
        graph = f"[0:v:0][0:s:{ordinal}]overlay[vout]"
    return ["-filter_complex", graph, "-map", "[vout]"]
