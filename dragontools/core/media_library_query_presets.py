from __future__ import annotations

from typing import Any

from .media_library_query_filters import append_nfo_filter
from .media_library_query_fragments import _SearchSqlFragments

_AUDIO_CODEC_PRESETS = {
    "aac": ("aac",),
    "ac3": ("ac3", "a52"),
    "eac3": ("eac3", "e-ac-3", "ec-3"),
    "truehd": ("truehd", "mlp"),
    "dts": ("dts", "dca"),
    "flac": ("flac",),
}


def _append_preset_filter(
    preset_key: str,
    deviation_criterion: str,
    where: list[str],
    params: list[Any],
    sql: _SearchSqlFragments,
) -> None:
    if deviation_criterion:
        return
    for handler in (
        _append_audio_preset,
        _append_dynamic_range_preset,
        _append_resolution_preset,
        _append_size_preset,
        _append_duration_preset,
        _append_video_codec_preset,
        _append_metadata_preset,
    ):
        if handler(preset_key, where, params, sql):
            return
    append_nfo_filter(preset_key, where)


def _append_audio_preset(
    preset: str,
    where: list[str],
    params: list[Any],
    sql: _SearchSqlFragments,
) -> bool:
    direct = {
        "has_german_audio": sql.german_audio_exists,
        "no_german_audio": f"NOT ({sql.german_audio_exists})",
        "multiple_audio": f"(SELECT COUNT(*) FROM media_streams a WHERE a.media_id=mi.id AND {sql.audio_type}) >= 2",
        "audio_stereo": f"EXISTS (SELECT 1 FROM media_streams a WHERE a.media_id=mi.id AND {sql.audio_type} AND a.channels=2)",
        "audio_51": f"EXISTS (SELECT 1 FROM media_streams a WHERE a.media_id=mi.id AND {sql.audio_type} AND a.channels=6)",
        "audio_71": f"EXISTS (SELECT 1 FROM media_streams a WHERE a.media_id=mi.id AND {sql.audio_type} AND a.channels>=8)",
        "audio_codec_unknown": f"EXISTS (SELECT 1 FROM media_streams a WHERE a.media_id=mi.id AND {sql.audio_type} AND trim(coalesce(a.codec, ''))='')",
    }
    predicate = direct.get(preset)
    if predicate:
        where.append(predicate)
        return True
    if not preset.startswith("audio_codec_"):
        return False
    codec_values = _AUDIO_CODEC_PRESETS.get(preset.removeprefix("audio_codec_"))
    if codec_values:
        placeholders = ",".join("?" for _ in codec_values)
        where.append(
            f"EXISTS (SELECT 1 FROM media_streams a WHERE a.media_id=mi.id "
            f"AND {sql.audio_type} AND lower(coalesce(a.codec, '')) IN ({placeholders}))"
        )
        params.extend(codec_values)
    return True


def _append_dynamic_range_preset(
    preset: str,
    where: list[str],
    _params: list[Any],
    sql: _SearchSqlFragments,
) -> bool:
    if preset == "dv":
        where.append(f"(mi.has_dolby_vision=1 OR {sql.dv_stream_exists})")
    elif preset == "hdr10plus":
        where.append(f"(mi.has_hdr10plus=1 OR {sql.hdr10plus_stream_exists})")
    elif preset == "hdr":
        where.append(f"(mi.is_hdr=1 OR {sql.hdr_stream_exists})")
    elif preset in {"sdr", "dynamic_range_unknown"}:
        where.append(
            f"mi.is_hdr=0 AND mi.has_hdr10plus=0 AND mi.has_dolby_vision=0 "
            f"AND NOT ({sql.hdr_stream_exists})"
        )
        known_sdr = (
            f"(({sql.explicit_sdr}) OR "
            "lower(coalesce(mi.analysis_status, '')) IN ('ok', 'jellyfin+scan'))"
        )
        where.append(known_sdr if preset == "sdr" else f"NOT {known_sdr}")
    else:
        return False
    return True


def _append_resolution_preset(
    preset: str,
    where: list[str],
    _params: list[Any],
    sql: _SearchSqlFragments,
) -> bool:
    if preset not in {
        "resolution_sd", "resolution_hd", "resolution_fhd", "resolution_qhd",
        "resolution_uhd", "four_k", "resolution_unknown",
    }:
        return False
    width, height = sql.width_value, sql.height_value
    if preset == "resolution_unknown":
        where.append(f"{width} <= 0 AND {height} <= 0")
    elif preset in {"resolution_uhd", "four_k"}:
        where.append(f"({width} >= 3000 OR {height} >= 1800)")
    elif preset == "resolution_qhd":
        where.append(f"NOT ({width} >= 3000 OR {height} >= 1800) AND ({width} >= 2300 OR {height} >= 1300)")
    elif preset == "resolution_fhd":
        where.append(f"NOT ({width} >= 2300 OR {height} >= 1300) AND ({width} >= 1600 OR {height} >= 900)")
    elif preset == "resolution_hd":
        where.append(f"NOT ({width} >= 1600 OR {height} >= 900) AND ({width} >= 1100 OR {height} >= 650)")
    else:
        where.append(f"({width} > 0 OR {height} > 0) AND {width} < 1100 AND {height} < 650")
    return True


def _append_size_preset(
    preset: str,
    where: list[str],
    params: list[Any],
    _sql: _SearchSqlFragments,
) -> bool:
    if preset not in {
        "size_under_1gb", "size_1_2gb", "size_2_5gb", "size_5_10gb",
        "size_10_20gb", "size_over_20gb", "size_unknown",
    }:
        return False
    gib = 1024 * 1024 * 1024
    if preset == "size_unknown":
        where.append("(mi.size_bytes IS NULL OR mi.size_bytes <= 0)")
    elif preset == "size_under_1gb":
        where.append("mi.size_bytes > 0 AND mi.size_bytes < ?")
        params.append(gib)
    elif preset == "size_1_2gb":
        where.append("mi.size_bytes >= ? AND mi.size_bytes < ?")
        params.extend((gib, 2 * gib))
    elif preset == "size_2_5gb":
        where.append("mi.size_bytes >= ? AND mi.size_bytes < ?")
        params.extend((2 * gib, 5 * gib))
    elif preset == "size_5_10gb":
        where.append("mi.size_bytes >= ? AND mi.size_bytes < ?")
        params.extend((5 * gib, 10 * gib))
    elif preset == "size_10_20gb":
        where.append("mi.size_bytes >= ? AND mi.size_bytes < ?")
        params.extend((10 * gib, 20 * gib))
    else:
        where.append("mi.size_bytes >= ?")
        params.append(20 * gib)
    return True


def _append_duration_preset(
    preset: str,
    where: list[str],
    _params: list[Any],
    _sql: _SearchSqlFragments,
) -> bool:
    predicates = {
        "duration_over_5h": "mi.duration_s > 18000",
        "duration_under_1min": "mi.duration_s > 0 AND mi.duration_s < 60",
        "duration_unknown": "(mi.duration_s IS NULL OR mi.duration_s <= 0)",
    }
    predicate = predicates.get(preset)
    if not predicate:
        return False
    where.append(predicate)
    return True


def _append_video_codec_preset(
    preset: str,
    where: list[str],
    _params: list[Any],
    sql: _SearchSqlFragments,
) -> bool:
    if preset not in {"h264", "hevc", "av1", "video_codec_unknown"}:
        return False
    value = f"lower(coalesce({sql.video_codec_value}, ''))"
    if preset == "h264":
        where.append(f"{value} IN ('h264', 'avc', 'avc1')")
    elif preset == "hevc":
        where.append(f"{value} IN ('hevc', 'h265', 'h.265', 'hev1', 'hvc1')")
    elif preset == "av1":
        where.append(f"{value} IN ('av1', 'av01')")
    else:
        where.append(f"trim(coalesce({sql.video_codec_value}, ''))='' ")
    return True


def _append_metadata_preset(
    preset: str,
    where: list[str],
    _params: list[Any],
    sql: _SearchSqlFragments,
) -> bool:
    if preset == "metadata_incomplete":
        where.append(
            f"(trim(coalesce({sql.video_codec_value}, ''))='' "
            f"OR ({sql.width_value} <= 0 AND {sql.height_value} <= 0) "
            f"OR NOT ({sql.video_exists}) "
            f"OR NOT EXISTS (SELECT 1 FROM media_streams a WHERE a.media_id=mi.id AND {sql.audio_type}) "
            "OR trim(coalesce(mi.title, mi.filename, ''))='')"
        )
        return True
    if preset == "video_properties_unknown":
        where.append(
            f"(NOT ({sql.video_exists}) OR trim(coalesce({sql.video_codec_value}, ''))='' "
            f"OR ({sql.width_value} <= 0 AND {sql.height_value} <= 0))"
        )
        return True
    return False
