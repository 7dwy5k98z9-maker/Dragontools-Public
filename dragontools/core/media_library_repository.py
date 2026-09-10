from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable

from .media_library_db import _connect, _create_schema, initialize_database
from .media_library_types import _now, default_media_library_db_path
from .media_library_utils import _infer_item_type, _int_or_none, _normalize_stream_type, _normalize_title
from .models import MediaInfo
from .paths import path_compare_key

_LOG = logging.getLogger(__name__)

def _insert_item(conn: sqlite3.Connection, item: dict[str, Any], streams: list[dict[str, Any]]) -> int:
    now = _now()
    item.setdefault("created_at", now)
    item["updated_at"] = now
    item.setdefault("exists_flag", 1)
    item.setdefault("active", item.get("exists_flag", 1))
    conn.execute(
        """
        INSERT INTO media_items(
            item_type, title, series_title, season, episode, year, source, source_id, provider,
            path, parent_path, filename, normalized_title, container, duration_s, size_bytes,
            width, height, video_codec, video_bitrate, overall_bitrate, is_hdr, has_hdr10plus,
            has_dolby_vision, dv_profile, nfo_status, trickplay_status, analysis_status,
            exists_flag, active, created_at, updated_at
        )
        VALUES(
            :item_type, :title, :series_title, :season, :episode, :year, :source, :source_id,
            :provider, :path, :parent_path, :filename, :normalized_title, :container,
            :duration_s, :size_bytes, :width, :height, :video_codec, :video_bitrate,
            :overall_bitrate, :is_hdr, :has_hdr10plus, :has_dolby_vision, :dv_profile,
            :nfo_status, :trickplay_status, :analysis_status, :exists_flag, :active, :created_at,
            :updated_at
        )
        ON CONFLICT(path) DO UPDATE SET
            item_type=excluded.item_type,
            title=excluded.title,
            series_title=excluded.series_title,
            season=excluded.season,
            episode=excluded.episode,
            year=excluded.year,
            source=excluded.source,
            source_id=excluded.source_id,
            provider=excluded.provider,
            parent_path=excluded.parent_path,
            filename=excluded.filename,
            normalized_title=excluded.normalized_title,
            container=excluded.container,
            duration_s=excluded.duration_s,
            size_bytes=excluded.size_bytes,
            width=excluded.width,
            height=excluded.height,
            video_codec=excluded.video_codec,
            video_bitrate=excluded.video_bitrate,
            overall_bitrate=excluded.overall_bitrate,
            is_hdr=excluded.is_hdr,
            has_hdr10plus=excluded.has_hdr10plus,
            has_dolby_vision=excluded.has_dolby_vision,
            dv_profile=excluded.dv_profile,
            nfo_status=excluded.nfo_status,
            trickplay_status=excluded.trickplay_status,
            analysis_status=excluded.analysis_status,
            exists_flag=excluded.exists_flag,
            active=excluded.active,
            updated_at=excluded.updated_at
        """,
        item,
    )
    media_id = int(conn.execute("SELECT id FROM media_items WHERE path=?", (item["path"],)).fetchone()["id"])
    conn.execute("DELETE FROM media_streams WHERE media_id=?", (media_id,))
    for stream in streams:
        stream_row = dict(stream)
        for key, value in {
            "profile": None,
            "duration_s": None,
            "frame_count": None,
            "frame_rate": None,
            "frame_rate_mode": None,
            "color_space": None,
            "color_transfer": None,
            "color_primaries": None,
        }.items():
            stream_row.setdefault(key, value)
        stream_row["stream_type"] = _normalize_stream_type(
            stream_row.get("stream_type"),
            codec=stream_row.get("codec"),
            channels=stream_row.get("channels"),
            width=stream_row.get("width"),
            height=stream_row.get("height"),
        )
        conn.execute(
            """
            INSERT INTO media_streams(
                media_id, stream_type, stream_index, codec, language, forced, channels,
                channel_layout, bitrate, width, height, hdr_format, dv_profile, pix_fmt,
                bit_depth, profile, duration_s, frame_count, frame_rate, frame_rate_mode,
                color_space, color_transfer, color_primaries, title
            )
            VALUES(:media_id, :stream_type, :stream_index, :codec, :language, :forced, :channels,
                :channel_layout, :bitrate, :width, :height, :hdr_format, :dv_profile,
                :pix_fmt, :bit_depth, :profile, :duration_s, :frame_count, :frame_rate,
                :frame_rate_mode, :color_space, :color_transfer, :color_primaries, :title)
            """,
            {"media_id": media_id, **stream_row},
        )
    return media_id


def _streams_from_media_info(info: MediaInfo) -> list[dict[str, Any]]:
    streams: list[dict[str, Any]] = []
    for idx, stream in enumerate(info.video_streams):
        streams.append(
            {
                "stream_type": "Video",
                "stream_index": idx,
                "codec": stream.codec,
                "language": None,
                "forced": 0,
                "channels": None,
                "channel_layout": None,
                "bitrate": stream.bitrate,
                "width": stream.width,
                "height": stream.height,
                "hdr_format": stream.hdr_format,
                "dv_profile": info.dolby_vision_profile,
                "pix_fmt": stream.pix_fmt,
                "bit_depth": stream.bit_depth,
                "profile": stream.profile,
                "duration_s": stream.duration_s,
                "frame_count": stream.frame_count,
                "frame_rate": stream.frame_rate,
                "frame_rate_mode": stream.frame_rate_mode,
                "color_space": stream.color_space,
                "color_transfer": stream.color_transfer,
                "color_primaries": stream.color_primaries,
                "title": None,
            }
        )
    for idx, stream in enumerate(info.audio_streams):
        streams.append(
            {
                "stream_type": "Audio",
                "stream_index": idx,
                "codec": stream.codec,
                "language": stream.language,
                "forced": 0,
                "channels": stream.channels,
                "channel_layout": stream.channel_layout,
                "bitrate": stream.bitrate,
                "width": None,
                "height": None,
                "hdr_format": None,
                "dv_profile": None,
                "pix_fmt": None,
                "bit_depth": None,
                "profile": None,
                "duration_s": None,
                "frame_count": None,
                "frame_rate": None,
                "frame_rate_mode": None,
                "color_space": None,
                "color_transfer": None,
                "color_primaries": None,
                "title": stream.title,
            }
        )
    for idx, stream in enumerate(info.subtitle_streams):
        streams.append(
            {
                "stream_type": "Subtitle",
                "stream_index": idx,
                "codec": stream.codec,
                "language": stream.language,
                "forced": 1 if stream.forced else 0,
                "channels": None,
                "channel_layout": None,
                "bitrate": None,
                "width": None,
                "height": None,
                "hdr_format": None,
                "dv_profile": None,
                "pix_fmt": None,
                "bit_depth": None,
                "profile": None,
                "duration_s": stream.duration_s,
                "frame_count": None,
                "frame_rate": None,
                "frame_rate_mode": None,
                "color_space": None,
                "color_transfer": None,
                "color_primaries": None,
                "title": stream.title,
            }
        )
    return streams


def _item_from_media_info(path: str | Path, info: MediaInfo, source: str = "dragontools") -> dict[str, Any]:
    file_path = Path(path)
    title = file_path.stem
    item_type = _infer_item_type("", str(file_path))
    series_title = None
    season = None
    episode = None
    try:
        from ..rules.move_rules import parse_series_match_details

        parsed = parse_series_match_details(str(file_path))
        if parsed:
            series_title = parsed.get("series")
            season = parsed.get("season")
            episode = parsed.get("episode")
            item_type = "episode"
    except Exception:
        _LOG.warning(
            "Serienmetadaten konnten fuer %s nicht aus dem Dateinamen abgeleitet werden.",
            file_path,
            exc_info=True,
        )
    video = info.video_streams[0] if info.video_streams else None
    try:
        size_bytes = int(file_path.stat().st_size)
    except OSError:
        size_bytes = _int_or_none(getattr(info, "size_bytes", None))
    return {
        "item_type": item_type,
        "title": title,
        "series_title": series_title,
        "season": season,
        "episode": episode,
        "year": None,
        "source": source,
        "source_id": None,
        "provider": None,
        "path": str(file_path),
        "parent_path": str(file_path.parent),
        "filename": file_path.name,
        "normalized_title": _normalize_title(series_title or title),
        "container": file_path.suffix.lstrip(".").lower(),
        "duration_s": info.duration_s,
        "size_bytes": size_bytes,
        "width": video.width if video else None,
        "height": video.height if video else None,
        "video_codec": video.codec if video else None,
        "video_bitrate": video.bitrate if video else None,
        "overall_bitrate": _average_bitrate(size_bytes, info.duration_s),
        "is_hdr": 1 if info.is_hdr else 0,
        "has_hdr10plus": 1 if info.has_hdr10plus else 0,
        "has_dolby_vision": 1 if info.dolby_vision else 0,
        "dv_profile": info.dolby_vision_profile,
        "nfo_status": "unknown",
        "trickplay_status": "unknown",
        "analysis_status": "ok",
        "exists_flag": 1,
        "active": 1,
    }


def _average_bitrate(size_bytes: int | None, duration_s: float | None) -> int | None:
    try:
        size = int(size_bytes or 0)
        duration = float(duration_s or 0.0)
    except (TypeError, ValueError):
        return None
    if size <= 0 or duration <= 0:
        return None
    return int(round((size * 8.0) / duration))


def _fallback_item_from_path(path: str | Path, source: str = "storage_scan") -> dict[str, Any]:
    """Minimaler DB-Eintrag, wenn MediaInfo/ffprobe eine Datei nicht analysieren kann."""
    file_path = Path(path)
    title = file_path.stem
    item_type = _infer_item_type("", str(file_path))
    series_title = None
    season = None
    episode = None
    try:
        from ..rules.move_rules import parse_series_match_details

        parsed = parse_series_match_details(str(file_path))
        if parsed:
            series_title = parsed.get("series")
            season = parsed.get("season")
            episode = parsed.get("episode")
            item_type = "episode"
    except Exception:
        _LOG.warning(
            "Serienmetadaten konnten fuer %s im Fallback-Pfad nicht abgeleitet werden.",
            file_path,
            exc_info=True,
        )
    try:
        size_bytes = file_path.stat().st_size
    except OSError:
        size_bytes = None
    return {
        "item_type": item_type,
        "title": title,
        "series_title": series_title,
        "season": season,
        "episode": episode,
        "year": None,
        "source": source,
        "source_id": None,
        "provider": None,
        "path": str(file_path),
        "parent_path": str(file_path.parent),
        "filename": file_path.name,
        "normalized_title": _normalize_title(series_title or title),
        "container": file_path.suffix.lstrip(".").lower(),
        "duration_s": None,
        "size_bytes": size_bytes,
        "width": None,
        "height": None,
        "video_codec": None,
        "video_bitrate": None,
        "overall_bitrate": None,
        "is_hdr": 0,
        "has_hdr10plus": 0,
        "has_dolby_vision": 0,
        "dv_profile": None,
        "nfo_status": "unknown",
        "trickplay_status": "unknown",
        "analysis_status": "analysis_failed",
        "exists_flag": 1,
        "active": 1,
    }


def record_media_file(db_path: str | Path, file_path: str | Path, tools: Any = None) -> None:
    from .media_analyzer import analyze_media

    db = initialize_database(db_path)
    info = analyze_media(str(file_path), tools=tools)
    item = _item_from_media_info(file_path, info)
    streams = _streams_from_media_info(info)
    with closing(_connect(db)) as conn:
        with conn:
            _create_schema(conn)
            _insert_item(conn, item, streams)
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('updated_at', ?)", (_now(),))


def _deactivate_paths(conn: sqlite3.Connection, paths: Iterable[str | Path]) -> int:
    unique: list[str] = []
    seen: set[str] = set()
    for path in paths:
        text = str(path or "")
        if not text:
            continue
        key = path_compare_key(text)
        if key in seen:
            continue
        seen.add(key)
        unique.append(text)
    if not unique:
        return 0
    changed = 0
    now = _now()
    for path in unique:
        cur = conn.execute(
            "UPDATE media_items SET exists_flag=0, active=0, updated_at=? WHERE path=?",
            (now, path),
        )
        changed += int(cur.rowcount or 0)
    return changed


def _deactivate_existing_episode_identity(conn: sqlite3.Connection, item: dict[str, Any]) -> int:
    if str(item.get("item_type") or "").casefold() != "episode":
        return 0
    try:
        from .move_conflicts import episode_identity_for_path

        identity = episode_identity_for_path(item.get("path") or item.get("filename") or "")
    except Exception:
        identity = None
    if identity is None:
        season = _int_or_none(item.get("season"))
        episode = _int_or_none(item.get("episode"))
        if season is None or episode is None:
            return 0
        target_episodes = (episode,)
    else:
        season = identity.season
        target_episodes = identity.episodes
    parent_path = str(item.get("parent_path") or "")
    normalized_title = str(item.get("normalized_title") or _normalize_title(item.get("series_title") or item.get("title")))
    rows = conn.execute(
        """
        SELECT id, path, filename, season, episode
        FROM media_items
        WHERE active=1
          AND exists_flag=1
          AND item_type='episode'
          AND season=?
          AND path<>?
          AND (
              lower(coalesce(parent_path, ''))=lower(?)
              OR lower(coalesce(normalized_title, ''))=lower(?)
          )
        """,
        (season, str(item.get("path") or ""), parent_path, normalized_title),
    ).fetchall()
    ids: list[int] = []
    for row in rows:
        row_identity = None
        try:
            row_identity = episode_identity_for_path(row["path"] or row["filename"] or "")
        except Exception:
            row_identity = None
        if row_identity is not None:
            if row_identity.season != season or row_identity.episodes != target_episodes:
                continue
        elif (_int_or_none(row["episode"]),) != target_episodes:
            continue
        ids.append(int(row["id"]))
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    cur = conn.execute(
        f"UPDATE media_items SET exists_flag=0, active=0, updated_at=? WHERE id IN ({placeholders})",
        (_now(), *ids),
    )
    return int(cur.rowcount or 0)


def record_moved_file(
    db_path: str | Path,
    source_path: str | Path,
    dest_path: str | Path,
    tools: Any = None,
    replaced_paths: Iterable[str | Path] = (),
) -> None:
    from .media_analyzer import analyze_media

    db = initialize_database(db_path)
    dest = Path(dest_path)
    if not dest.exists():
        raise FileNotFoundError(f"Zieldatei nicht gefunden: {dest}")
    info = analyze_media(str(dest), tools=tools)
    item = _item_from_media_info(dest, info)
    streams = _streams_from_media_info(info)
    with closing(_connect(db)) as conn:
        with conn:
            _create_schema(conn)
            _deactivate_paths(conn, [source_path, *list(replaced_paths or [])])
            _deactivate_existing_episode_identity(conn, item)
            _insert_item(conn, item, streams)
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('updated_at', ?)", (_now(),))


def record_moved_file_from_settings(
    settings: Any,
    source_path: str | Path,
    dest_path: str | Path,
    tools: Any = None,
    replaced_paths: Iterable[str | Path] = (),
) -> bool:
    from .settings import (
        SET_KEY_MEDIA_LIBRARY_DB_PATH,
        SET_KEY_MEDIA_LIBRARY_ENABLED,
    )

    enabled = settings.value(SET_KEY_MEDIA_LIBRARY_ENABLED, False, type=bool)
    if not enabled:
        return False
    db_path = settings.value(SET_KEY_MEDIA_LIBRARY_DB_PATH, str(default_media_library_db_path()), type=str)
    if not db_path:
        return False
    record_moved_file(db_path, source_path, dest_path, tools=tools, replaced_paths=replaced_paths)
    return True
