from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .media_library_scope import _mapping_prefixes_for_scope, _path_prefix_condition
from .media_library_utils import _AUDIO_CODECS, _SUBTITLE_CODECS, _VIDEO_CODECS, _normalize_title

def _stream_type_condition(alias: str, expected: str) -> str:
    value = f"lower(trim(coalesce({alias}.stream_type, '')))"
    codec = f"lower(trim(coalesce({alias}.codec, '')))"
    width = f"coalesce({alias}.width, 0)"
    height = f"coalesce({alias}.height, 0)"
    channels = f"coalesce({alias}.channels, 0)"
    if expected == "audio":
        audio_codecs = ",".join(f"'{codec}'" for codec in sorted(_AUDIO_CODECS))
        return f"({value}='audio' OR ({value}='' AND {channels}>0) OR ({codec} IN ({audio_codecs})))"
    if expected == "video":
        video_codecs = ",".join(f"'{codec}'" for codec in sorted(_VIDEO_CODECS))
        return f"({value} IN ('video', '1') OR ({codec} IN ({video_codecs})) OR ({value}='' AND {width}>0 AND {height}>0 AND {channels}=0))"
    if expected == "subtitle":
        subtitle_codecs = ",".join(f"'{codec}'" for codec in sorted(_SUBTITLE_CODECS))
        return f"({value} IN ('subtitle', 'subtitles', '2') OR ({codec} IN ({subtitle_codecs})))"
    return "0"


@dataclass(frozen=True)
class _SearchSqlFragments:
    audio_type: str
    audio_type_s: str
    video_type_s: str
    subtitle_type: str
    german_audio_exists: str
    video_exists: str
    explicit_sdr: str
    hdr_stream_exists: str
    hdr10plus_stream_exists: str
    dv_stream_exists: str
    video_codec_value: str
    width_value: str
    height_value: str


def _build_search_sql_fragments() -> _SearchSqlFragments:
    audio_type = _stream_type_condition("a", "audio")
    video_type = _stream_type_condition("v", "video")
    audio_type_s = _stream_type_condition("s", "audio")
    video_type_s = _stream_type_condition("s", "video")
    subtitle_type = _stream_type_condition("s", "subtitle")
    german_audio_exists = """
        EXISTS (
            SELECT 1 FROM media_streams a
            WHERE a.media_id=mi.id
              AND {audio_type}
              AND (
                  lower(coalesce(a.language, '')) IN ('de', 'deu', 'ger', 'german', 'deutsch')
                  OR lower(coalesce(a.language, '')) LIKE 'de-%'
              )
        )
    """.format(audio_type=audio_type)
    video_exists = """
        EXISTS (
            SELECT 1 FROM media_streams v
            WHERE v.media_id=mi.id AND {video_type}
        )
    """.format(video_type=video_type)
    explicit_sdr = """
        EXISTS (
            SELECT 1 FROM media_streams v
            WHERE v.media_id=mi.id
              AND {video_type}
              AND (
                  lower(coalesce(v.hdr_format, '')) LIKE '%sdr%'
                  OR lower(coalesce(v.hdr_format, '')) LIKE '%bt709%'
                  OR lower(coalesce(v.hdr_format, '')) LIKE '%bt.709%'
                  OR lower(coalesce(v.hdr_format, '')) LIKE '%rec709%'
                  OR lower(coalesce(v.hdr_format, '')) LIKE '%rec.709%'
              )
        )
    """.format(video_type=video_type)
    hdr_stream_exists = """
        EXISTS (
            SELECT 1 FROM media_streams v
            WHERE v.media_id=mi.id
              AND {video_type}
              AND (
                  lower(coalesce(v.hdr_format, '')) LIKE '%hdr%'
                  OR lower(coalesce(v.hdr_format, '')) LIKE '%bt2020%'
                  OR lower(coalesce(v.hdr_format, '')) LIKE '%pq%'
                  OR lower(coalesce(v.hdr_format, '')) LIKE '%hlg%'
                  OR lower(coalesce(v.hdr_format, '')) LIKE '%dolby%'
                  OR lower(coalesce(v.hdr_format, '')) LIKE '%smpte2084%'
                  OR lower(coalesce(v.hdr_format, '')) LIKE '%st2084%'
                  OR lower(coalesce(v.dv_profile, '')) <> ''
              )
        )
    """.format(video_type=video_type)
    hdr10plus_stream_exists = """
        EXISTS (
            SELECT 1 FROM media_streams v
            WHERE v.media_id=mi.id
              AND {video_type}
              AND (
                  lower(coalesce(v.hdr_format, '')) LIKE '%hdr10+%'
                  OR lower(coalesce(v.hdr_format, '')) LIKE '%hdr10plus%'
                  OR lower(coalesce(v.hdr_format, '')) LIKE '%dynamic metadata%'
                  OR lower(coalesce(v.hdr_format, '')) LIKE '%2094-40%'
                  OR lower(coalesce(v.hdr_format, '')) LIKE '%st2094%'
              )
        )
    """.format(video_type=video_type)
    dv_stream_exists = """
        EXISTS (
            SELECT 1 FROM media_streams v
            WHERE v.media_id=mi.id
              AND {video_type}
              AND (
                  lower(coalesce(v.hdr_format, '')) LIKE '%dolby vision%'
                  OR lower(coalesce(v.hdr_format, '')) LIKE '%dovi%'
                  OR lower(coalesce(v.hdr_format, '')) LIKE '%dvhe%'
                  OR lower(coalesce(v.dv_profile, '')) <> ''
              )
        )
    """.format(video_type=video_type)
    video_codec_value = f"""
        coalesce(
            nullif(mi.video_codec, ''),
            (SELECT v.codec FROM media_streams v WHERE v.media_id=mi.id AND {video_type}
             ORDER BY coalesce(v.stream_index, 999999), v.id LIMIT 1)
        )
    """
    width_value = f"""
        coalesce(
            nullif(mi.width, 0),
            (SELECT v.width FROM media_streams v WHERE v.media_id=mi.id AND {video_type}
             ORDER BY coalesce(v.stream_index, 999999), v.id LIMIT 1),
            0
        )
    """
    height_value = f"""
        coalesce(
            nullif(mi.height, 0),
            (SELECT v.height FROM media_streams v WHERE v.media_id=mi.id AND {video_type}
             ORDER BY coalesce(v.stream_index, 999999), v.id LIMIT 1),
            0
        )
    """
    return _SearchSqlFragments(
        audio_type=audio_type,
        audio_type_s=audio_type_s,
        video_type_s=video_type_s,
        subtitle_type=subtitle_type,
        german_audio_exists=german_audio_exists,
        video_exists=video_exists,
        explicit_sdr=explicit_sdr,
        hdr_stream_exists=hdr_stream_exists,
        hdr10plus_stream_exists=hdr10plus_stream_exists,
        dv_stream_exists=dv_stream_exists,
        video_codec_value=video_codec_value,
        width_value=width_value,
        height_value=height_value,
    )


def _append_media_type_filter(where: list[str], media_type_key: str) -> None:
    if media_type_key == "videos":
        where.append("mi.item_type IN ('episode', 'movie', 'video')")
    elif media_type_key == "movies":
        where.append("mi.item_type='movie'")
    elif media_type_key == "series":
        where.append("mi.item_type='series'")
    elif media_type_key == "seasons":
        where.append("mi.item_type='season'")
    elif media_type_key == "episodes":
        where.append("mi.item_type='episode'")
    elif media_type_key == "folders":
        where.append("mi.item_type='folder'")


def _append_scope_filter(
    db: Path,
    scope_key: str,
    where: list[str],
    params: list[Any],
) -> None:
    if scope_key in {"all", ""}:
        return
    if scope_key in {"movies", "filme", "film"}:
        prefixes = _mapping_prefixes_for_scope(db, "movies")
        condition = _path_prefix_condition(prefixes, params)
        where.append(f"(mi.item_type='movie'{(' OR ' + condition) if condition else ''})")
    elif scope_key == "anime":
        condition = _path_prefix_condition(_mapping_prefixes_for_scope(db, "anime"), params)
        where.append(condition or "0")
    elif scope_key == "tv":
        condition = _path_prefix_condition(_mapping_prefixes_for_scope(db, "tv"), params)
        where.append(condition or "0")
    elif scope_key in {"series", "serien"}:
        prefixes = _mapping_prefixes_for_scope(db, "anime") + _mapping_prefixes_for_scope(db, "tv")
        condition = _path_prefix_condition(prefixes, params)
        where.append(f"(mi.item_type IN ('series', 'season', 'episode'){(' OR ' + condition) if condition else ''})")
    elif scope_key == "other":
        all_prefixes: list[str] = []
        for key in ("movies", "anime", "tv"):
            all_prefixes.extend(_mapping_prefixes_for_scope(db, key))
        condition = _path_prefix_condition(all_prefixes, params)
        if condition:
            where.append(f"NOT {condition}")


def _append_preset_filter(
    preset_key: str,
    deviation_criterion: str,
    where: list[str],
    params: list[Any],
    sql: _SearchSqlFragments,
) -> None:
    if deviation_criterion:
        return
    if preset_key == "has_german_audio":
        where.append(sql.german_audio_exists)
    elif preset_key == "no_german_audio":
        where.append(f"NOT ({sql.german_audio_exists})")
    elif preset_key == "multiple_audio":
        where.append(f"(SELECT COUNT(*) FROM media_streams a WHERE a.media_id=mi.id AND {sql.audio_type}) >= 2")
    elif preset_key == "audio_stereo":
        where.append(f"EXISTS (SELECT 1 FROM media_streams a WHERE a.media_id=mi.id AND {sql.audio_type} AND a.channels=2)")
    elif preset_key == "audio_51":
        where.append(f"EXISTS (SELECT 1 FROM media_streams a WHERE a.media_id=mi.id AND {sql.audio_type} AND a.channels=6)")
    elif preset_key == "audio_71":
        where.append(f"EXISTS (SELECT 1 FROM media_streams a WHERE a.media_id=mi.id AND {sql.audio_type} AND a.channels>=8)")
    elif preset_key.startswith("audio_codec_"):
        codec = preset_key.removeprefix("audio_codec_")
        codec_values = {
            "aac": ("aac",),
            "ac3": ("ac3", "a52"),
            "eac3": ("eac3", "e-ac-3", "ec-3"),
            "truehd": ("truehd", "mlp"),
            "dts": ("dts", "dca"),
            "flac": ("flac",),
        }.get(codec)
        if codec_values:
            placeholders = ",".join("?" for _ in codec_values)
            where.append(
                f"EXISTS (SELECT 1 FROM media_streams a WHERE a.media_id=mi.id AND {sql.audio_type} AND lower(coalesce(a.codec, '')) IN ({placeholders}))"
            )
            params.extend(codec_values)
    elif preset_key == "audio_codec_unknown":
        where.append(
            f"EXISTS (SELECT 1 FROM media_streams a WHERE a.media_id=mi.id AND {sql.audio_type} AND trim(coalesce(a.codec, ''))='')"
        )
    elif preset_key == "dv":
        where.append(f"(mi.has_dolby_vision=1 OR {sql.dv_stream_exists})")
    elif preset_key == "hdr10plus":
        where.append(f"(mi.has_hdr10plus=1 OR {sql.hdr10plus_stream_exists})")
    elif preset_key == "hdr":
        where.append(f"(mi.is_hdr=1 OR {sql.hdr_stream_exists})")
    elif preset_key == "sdr":
        where.append(f"mi.is_hdr=0 AND mi.has_hdr10plus=0 AND mi.has_dolby_vision=0 AND NOT ({sql.hdr_stream_exists})")
        where.append(f"(({sql.explicit_sdr}) OR lower(coalesce(mi.analysis_status, '')) IN ('ok', 'jellyfin+scan'))")
    elif preset_key == "dynamic_range_unknown":
        where.append(f"mi.is_hdr=0 AND mi.has_hdr10plus=0 AND mi.has_dolby_vision=0 AND NOT ({sql.hdr_stream_exists})")
        where.append(f"NOT (({sql.explicit_sdr}) OR lower(coalesce(mi.analysis_status, '')) IN ('ok', 'jellyfin+scan'))")
    elif preset_key in {"resolution_sd", "resolution_hd", "resolution_fhd", "resolution_qhd", "resolution_uhd", "four_k", "resolution_unknown"}:
        width = sql.width_value
        height = sql.height_value
        if preset_key == "resolution_unknown":
            where.append(f"{width} <= 0 AND {height} <= 0")
        elif preset_key in {"resolution_uhd", "four_k"}:
            where.append(f"({width} >= 3000 OR {height} >= 1800)")
        elif preset_key == "resolution_qhd":
            where.append(f"NOT ({width} >= 3000 OR {height} >= 1800) AND ({width} >= 2300 OR {height} >= 1300)")
        elif preset_key == "resolution_fhd":
            where.append(f"NOT ({width} >= 2300 OR {height} >= 1300) AND ({width} >= 1600 OR {height} >= 900)")
        elif preset_key == "resolution_hd":
            where.append(f"NOT ({width} >= 1600 OR {height} >= 900) AND ({width} >= 1100 OR {height} >= 650)")
        else:
            where.append(f"({width} > 0 OR {height} > 0) AND {width} < 1100 AND {height} < 650")
    elif preset_key in {
        "size_under_1gb",
        "size_1_2gb",
        "size_2_5gb",
        "size_5_10gb",
        "size_10_20gb",
        "size_over_20gb",
        "size_unknown",
    }:
        gib = 1024 * 1024 * 1024
        if preset_key == "size_unknown":
            where.append("(mi.size_bytes IS NULL OR mi.size_bytes <= 0)")
        elif preset_key == "size_under_1gb":
            where.append("mi.size_bytes > 0 AND mi.size_bytes < ?")
            params.append(gib)
        elif preset_key == "size_1_2gb":
            where.append("mi.size_bytes >= ? AND mi.size_bytes < ?")
            params.extend((gib, 2 * gib))
        elif preset_key == "size_2_5gb":
            where.append("mi.size_bytes >= ? AND mi.size_bytes < ?")
            params.extend((2 * gib, 5 * gib))
        elif preset_key == "size_5_10gb":
            where.append("mi.size_bytes >= ? AND mi.size_bytes < ?")
            params.extend((5 * gib, 10 * gib))
        elif preset_key == "size_10_20gb":
            where.append("mi.size_bytes >= ? AND mi.size_bytes < ?")
            params.extend((10 * gib, 20 * gib))
        else:
            where.append("mi.size_bytes >= ?")
            params.append(20 * gib)
    elif preset_key in {"duration_over_5h", "duration_under_1min", "duration_unknown"}:
        if preset_key == "duration_over_5h":
            where.append("mi.duration_s > 18000")
        elif preset_key == "duration_under_1min":
            where.append("mi.duration_s > 0 AND mi.duration_s < 60")
        else:
            where.append("(mi.duration_s IS NULL OR mi.duration_s <= 0)")
    elif preset_key in {"h264", "hevc", "av1", "video_codec_unknown"}:
        if preset_key == "h264":
            where.append(f"lower(coalesce({sql.video_codec_value}, '')) IN ('h264', 'avc', 'avc1')")
        elif preset_key == "hevc":
            where.append(f"lower(coalesce({sql.video_codec_value}, '')) IN ('hevc', 'h265', 'h.265', 'hev1', 'hvc1')")
        elif preset_key == "av1":
            where.append(f"lower(coalesce({sql.video_codec_value}, '')) IN ('av1', 'av01')")
        else:
            where.append(f"trim(coalesce({sql.video_codec_value}, ''))='' ")
    elif preset_key == "metadata_incomplete":
        where.append(
            f"(trim(coalesce({sql.video_codec_value}, ''))='' "
            f"OR ({sql.width_value} <= 0 AND {sql.height_value} <= 0) "
            f"OR NOT ({sql.video_exists}) "
            f"OR NOT EXISTS (SELECT 1 FROM media_streams a WHERE a.media_id=mi.id AND {sql.audio_type}) "
            "OR trim(coalesce(mi.title, mi.filename, ''))='')"
        )
    elif preset_key == "video_properties_unknown":
        where.append(
            f"(NOT ({sql.video_exists}) OR trim(coalesce({sql.video_codec_value}, ''))='' OR ({sql.width_value} <= 0 AND {sql.height_value} <= 0))"
        )


def _append_text_filter(where: list[str], params: list[Any], text: str) -> None:
    if not text.strip():
        return
    needle = f"%{text.strip().casefold()}%"
    normalized_needle = f"%{_normalize_title(text.strip())}%"
    where.append(
        """
        (
            lower(coalesce(mi.title, '')) LIKE ?
            OR lower(coalesce(mi.series_title, '')) LIKE ?
            OR lower(coalesce(mi.filename, '')) LIKE ?
            OR lower(coalesce(mi.path, '')) LIKE ?
            OR lower(coalesce(mi.normalized_title, '')) LIKE ?
        )
        """
    )
    params.extend([needle, needle, needle, needle, normalized_needle])


def _build_search_query(
    where: list[str],
    *,
    deviation_criterion: str,
    sql: _SearchSqlFragments,
) -> str:
    video_type_v = _stream_type_condition("v", "video")
    query = f"""
        SELECT
            mi.item_type, mi.title, mi.series_title, mi.season, mi.episode, mi.year,
            mi.container, mi.duration_s, mi.video_bitrate, mi.overall_bitrate,
            mi.nfo_status, mi.trickplay_status,
            {sql.video_codec_value} AS video_codec,
            {sql.width_value} AS width,
            {sql.height_value} AS height,
            CASE WHEN (mi.is_hdr=1 OR {sql.hdr_stream_exists}) THEN 1 ELSE 0 END AS is_hdr,
            CASE WHEN (mi.has_hdr10plus=1 OR {sql.hdr10plus_stream_exists}) THEN 1 ELSE 0 END AS has_hdr10plus,
            CASE WHEN (mi.has_dolby_vision=1 OR {sql.dv_stream_exists}) THEN 1 ELSE 0 END AS has_dolby_vision,
            mi.size_bytes, mi.analysis_status, mi.path, mi.parent_path, mi.filename,
            (SELECT v.profile FROM media_streams v WHERE v.media_id=mi.id AND {video_type_v}
             ORDER BY coalesce(v.stream_index, 999999), v.id LIMIT 1) AS video_profile,
            (SELECT v.pix_fmt FROM media_streams v WHERE v.media_id=mi.id AND {video_type_v}
             ORDER BY coalesce(v.stream_index, 999999), v.id LIMIT 1) AS pix_fmt,
            (SELECT v.bit_depth FROM media_streams v WHERE v.media_id=mi.id AND {video_type_v}
             ORDER BY coalesce(v.stream_index, 999999), v.id LIMIT 1) AS bit_depth,
            (SELECT v.frame_rate FROM media_streams v WHERE v.media_id=mi.id AND {video_type_v}
             ORDER BY coalesce(v.stream_index, 999999), v.id LIMIT 1) AS frame_rate,
            (SELECT v.frame_rate_mode FROM media_streams v WHERE v.media_id=mi.id AND {video_type_v}
             ORDER BY coalesce(v.stream_index, 999999), v.id LIMIT 1) AS frame_rate_mode,
            (SELECT v.frame_count FROM media_streams v WHERE v.media_id=mi.id AND {video_type_v}
             ORDER BY coalesce(v.stream_index, 999999), v.id LIMIT 1) AS frame_count,
            (SELECT v.color_space FROM media_streams v WHERE v.media_id=mi.id AND {video_type_v}
             ORDER BY coalesce(v.stream_index, 999999), v.id LIMIT 1) AS color_space,
            (SELECT v.color_transfer FROM media_streams v WHERE v.media_id=mi.id AND {video_type_v}
             ORDER BY coalesce(v.stream_index, 999999), v.id LIMIT 1) AS color_transfer,
            (SELECT v.color_primaries FROM media_streams v WHERE v.media_id=mi.id AND {video_type_v}
             ORDER BY coalesce(v.stream_index, 999999), v.id LIMIT 1) AS color_primaries,
            CASE WHEN {sql.german_audio_exists} THEN 1 ELSE 0 END AS has_german_audio,
            (SELECT COUNT(*) FROM media_streams a WHERE a.media_id=mi.id AND {sql.audio_type}) AS audio_track_count,
            (SELECT group_concat(coalesce(language, '?') || ':' || coalesce(codec, '?'), ', ')
               FROM media_streams s
              WHERE s.media_id=mi.id AND {sql.audio_type_s}) AS audio_summary,
            (SELECT group_concat(coalesce(codec, '?'), ',')
               FROM media_streams s
              WHERE s.media_id=mi.id AND {sql.audio_type_s}) AS audio_codecs,
            (SELECT group_concat(coalesce(CAST(channels AS TEXT), '?'), ',')
               FROM media_streams s
              WHERE s.media_id=mi.id AND {sql.audio_type_s}) AS audio_channels,
            (SELECT group_concat(
                        coalesce(language, '?') || ':' || coalesce(codec, '?') ||
                        CASE
                            WHEN lower(coalesce(source_kind, 'internal'))='external' THEN ':extern'
                            ELSE ':intern'
                        END,
                        ', '
                    )
               FROM media_streams s
              WHERE s.media_id=mi.id AND {sql.subtitle_type}) AS subtitle_summary,
            (SELECT group_concat(coalesce(hdr_format, ''), ',')
               FROM media_streams s
              WHERE s.media_id=mi.id AND {sql.video_type_s}) AS video_range
        FROM media_items mi
        WHERE {' AND '.join(where)}
        ORDER BY coalesce(mi.series_title, mi.title, mi.filename), mi.season, mi.episode
    """
    if not deviation_criterion:
        query += " LIMIT ?"
    return query
