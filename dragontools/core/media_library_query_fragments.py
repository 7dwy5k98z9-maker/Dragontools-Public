from __future__ import annotations

from dataclasses import dataclass

from .media_library_utils import _AUDIO_CODECS, _SUBTITLE_CODECS, _VIDEO_CODECS


def _stream_type_condition(alias: str, expected: str) -> str:
    value = f"lower(trim(coalesce({alias}.stream_type, '')))"
    codec = f"lower(trim(coalesce({alias}.codec, '')))"
    width = f"coalesce({alias}.width, 0)"
    height = f"coalesce({alias}.height, 0)"
    channels = f"coalesce({alias}.channels, 0)"
    if expected == "audio":
        audio_codecs = ",".join(f"'{item}'" for item in sorted(_AUDIO_CODECS))
        return f"({value}='audio' OR ({value}='' AND {channels}>0) OR ({codec} IN ({audio_codecs})))"
    if expected == "video":
        video_codecs = ",".join(f"'{item}'" for item in sorted(_VIDEO_CODECS))
        return (
            f"({value} IN ('video', '1') OR ({codec} IN ({video_codecs})) "
            f"OR ({value}='' AND {width}>0 AND {height}>0 AND {channels}=0))"
        )
    if expected == "subtitle":
        subtitle_codecs = ",".join(f"'{item}'" for item in sorted(_SUBTITLE_CODECS))
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
    return _SearchSqlFragments(
        audio_type=audio_type,
        audio_type_s=audio_type_s,
        video_type_s=video_type_s,
        subtitle_type=subtitle_type,
        german_audio_exists=_german_audio_exists(audio_type),
        video_exists=f"EXISTS (SELECT 1 FROM media_streams v WHERE v.media_id=mi.id AND {video_type})",
        explicit_sdr=_explicit_sdr(video_type),
        hdr_stream_exists=_hdr_stream_exists(video_type),
        hdr10plus_stream_exists=_hdr10plus_stream_exists(video_type),
        dv_stream_exists=_dv_stream_exists(video_type),
        video_codec_value=_first_video_value("codec", video_type, "nullif(mi.video_codec, '')"),
        width_value=_first_video_value("width", video_type, "nullif(mi.width, 0)", default="0"),
        height_value=_first_video_value("height", video_type, "nullif(mi.height, 0)", default="0"),
    )


def _german_audio_exists(audio_type: str) -> str:
    return f"""
        EXISTS (
            SELECT 1 FROM media_streams a
            WHERE a.media_id=mi.id
              AND {audio_type}
              AND (
                  lower(coalesce(a.language, '')) IN ('de', 'deu', 'ger', 'german', 'deutsch')
                  OR lower(coalesce(a.language, '')) LIKE 'de-%'
              )
        )
    """


def _explicit_sdr(video_type: str) -> str:
    return _video_exists_with_format_terms(video_type, ("sdr", "bt709", "bt.709", "rec709", "rec.709"))


def _hdr_stream_exists(video_type: str) -> str:
    base = _video_exists_with_format_terms(
        video_type,
        ("hdr", "bt2020", "pq", "hlg", "dolby", "smpte2084", "st2084"),
        closing_extra="OR lower(coalesce(v.dv_profile, '')) <> ''",
    )
    return base


def _hdr10plus_stream_exists(video_type: str) -> str:
    return _video_exists_with_format_terms(
        video_type,
        ("hdr10+", "hdr10plus", "dynamic metadata", "2094-40", "st2094"),
    )


def _dv_stream_exists(video_type: str) -> str:
    return _video_exists_with_format_terms(
        video_type,
        ("dolby vision", "dovi", "dvhe"),
        closing_extra="OR lower(coalesce(v.dv_profile, '')) <> ''",
    )


def _video_exists_with_format_terms(
    video_type: str,
    terms: tuple[str, ...],
    *,
    closing_extra: str = "",
) -> str:
    predicates = [f"lower(coalesce(v.hdr_format, '')) LIKE '%{term}%'" for term in terms]
    if closing_extra:
        predicates.append(closing_extra.removeprefix("OR "))
    joined = "\n                  OR ".join(predicates)
    return f"""
        EXISTS (
            SELECT 1 FROM media_streams v
            WHERE v.media_id=mi.id
              AND {video_type}
              AND (
                  {joined}
              )
        )
    """


def _first_video_value(column: str, video_type: str, preferred: str, *, default: str | None = None) -> str:
    fallback = f"""(SELECT v.{column} FROM media_streams v
             WHERE v.media_id=mi.id AND {video_type}
             ORDER BY coalesce(v.stream_index, 999999), v.id LIMIT 1)"""
    values = [preferred, fallback]
    if default is not None:
        values.append(default)
    return "coalesce(\n            " + ",\n            ".join(values) + "\n        )"
