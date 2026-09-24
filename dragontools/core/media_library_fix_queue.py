from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .media_library_db import _connect, initialize_database_once
from .media_library_sidecars import _nfo_status_for_path, _trickplay_status_for_path
from .media_library_types import _now


ACTION_GENERATE_NFO = "generate_nfo"
ACTION_GENERATE_TRICKPLAY = "generate_trickplay"
ACTION_REANALYZE = "reanalyze"
ACTION_DETECT_STREAM_LANGUAGE = "detect_stream_language"
ACTION_FIX_TRACK_TITLE = "fix_track_title"
ACTION_OCR_BITMAP_SUBTITLE = "ocr_bitmap_subtitle"


@dataclass(frozen=True)
class MediaLibraryFixIssue:
    media_id: int
    path: str
    title: str
    item_type: str
    issue_type: str
    action: str
    problem: str
    action_label: str
    detail: str = ""
    stream_id: int | None = None
    stream_index: int | None = None
    stream_type: str = ""
    stream_ordinal: int | None = None
    codec: str = ""
    language: str = ""
    track_title: str = ""
    forced: bool = False
    channels: int | None = None
    bitrate: int | None = None
    duration_s: float | None = None
    source_kind: str = "internal"
    external_path: str = ""
    nfo_path: str = ""
    source_signature: tuple[int, ...] = ()

    def __post_init__(self):
        if self.source_signature:
            return
        try:
            stat = Path(self.path).stat()
            signature = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
            object.__setattr__(self, "source_signature", signature)
        except OSError:
            pass  # Missing/unreadable sources are rejected at execution time.

    @property
    def key(self) -> str:
        stream_part = f":stream:{self.stream_id}" if self.stream_id is not None else ""
        return f"{self.media_id}{stream_part}:{self.action}"


@dataclass(frozen=True)
class MediaLibraryFixDiscoveryResult:
    issues: tuple[MediaLibraryFixIssue, ...]
    scanned_media: int
    truncated: bool


@dataclass(frozen=True)
class MediaLibraryFixOutcome:
    issue: MediaLibraryFixIssue
    status: str
    message: str
    artifact_path: str = ""
    report_path: str = ""

    @property
    def succeeded(self) -> bool:
        return self.status == "success"


_METADATA_PREDICATE = """(
    coalesce(mi.duration_s, 0) <= 0
    OR trim(coalesce(mi.video_codec, ''))=''
    OR (coalesce(mi.width, 0) <= 0 AND coalesce(mi.height, 0) <= 0)
    OR NOT EXISTS (
        SELECT 1 FROM media_streams v
        WHERE v.media_id=mi.id
          AND (
              lower(trim(coalesce(v.stream_type, ''))) IN ('video', '1')
              OR (coalesce(v.width, 0) > 0 AND coalesce(v.height, 0) > 0 AND coalesce(v.channels, 0)=0)
          )
    )
    OR NOT EXISTS (
        SELECT 1 FROM media_streams a
        WHERE a.media_id=mi.id
          AND (
              lower(trim(coalesce(a.stream_type, '')))='audio'
              OR coalesce(a.channels, 0) > 0
          )
    )
)"""


def _fix_candidate_sql(categories: set[str]) -> str:
    predicates: list[str] = []
    if "nfo" in categories:
        predicates.append("lower(coalesce(mi.nfo_status, 'unknown'))='missing'")
    if "trickplay" in categories:
        predicates.append("lower(coalesce(mi.trickplay_status, 'unknown')) IN ('missing', 'empty')")
    if "metadata" in categories:
        predicates.append(_METADATA_PREDICATE)
    if not predicates:
        return ""
    issue_filter = " OR ".join(f"({predicate})" for predicate in predicates)
    return f"""
        SELECT
            mi.id,
            mi.path,
            coalesce(mi.title, mi.filename, '') AS title,
            mi.item_type,
            mi.nfo_status,
            mi.trickplay_status,
            mi.duration_s,
            mi.video_codec,
            mi.width,
            mi.height,
            mi.analysis_status,
            EXISTS (
                SELECT 1 FROM media_streams v
                WHERE v.media_id=mi.id
                  AND (
                      lower(trim(coalesce(v.stream_type, ''))) IN ('video', '1')
                      OR (coalesce(v.width, 0) > 0 AND coalesce(v.height, 0) > 0 AND coalesce(v.channels, 0)=0)
                  )
            ) AS has_video,
            EXISTS (
                SELECT 1 FROM media_streams a
                WHERE a.media_id=mi.id
                  AND (
                      lower(trim(coalesce(a.stream_type, '')))='audio'
                      OR coalesce(a.channels, 0) > 0
                  )
            ) AS has_audio
        FROM media_items mi
        WHERE mi.active=1
          AND mi.exists_flag=1
          AND lower(coalesce(mi.item_type, '')) IN ('movie', 'episode', 'video')
          AND ({issue_filter})
        ORDER BY coalesce(mi.series_title, mi.title, mi.filename), mi.season, mi.episode, mi.id
        LIMIT ?
    """



def discover_fix_issues(
    db_path: str | Path,
    *,
    media_limit: int = 5000,
    categories: Iterable[str] = ("nfo", "trickplay", "metadata"),
) -> MediaLibraryFixDiscoveryResult:
    """Read database candidates and capture source identity without changing media."""
    selected_categories = {str(category).strip().casefold() for category in categories}
    selected_categories &= {"nfo", "trickplay", "metadata", "streams", "ocr"}
    if not selected_categories:
        return MediaLibraryFixDiscoveryResult(issues=(), scanned_media=0, truncated=False)
    db = initialize_database_once(db_path)
    limit = max(1, int(media_limit))
    issues: list[MediaLibraryFixIssue] = []
    media_ids: set[int] = set()
    truncated = False

    media_categories = selected_categories & {"nfo", "trickplay", "metadata"}
    if media_categories:
        query = _fix_candidate_sql(media_categories)
        with closing(_connect(db)) as conn:
            rows = conn.execute(query, (limit + 1,)).fetchall()
        truncated = len(rows) > limit
        for row in rows[:limit]:
            media_ids.add(int(row["id"]))
            issues.extend(_issues_from_row(row, media_categories))

    if "streams" in selected_categories or "ocr" in selected_categories:
        stream_issues, stream_media_ids, stream_truncated = _discover_stream_issues(
            db, limit=limit, include_stream_fixes="streams" in selected_categories, include_ocr="ocr" in selected_categories
        )
        issues.extend(stream_issues)
        media_ids.update(stream_media_ids)
        truncated = truncated or stream_truncated

    return MediaLibraryFixDiscoveryResult(
        issues=tuple(dedupe_fix_issues(issues)),
        scanned_media=len(media_ids),
        truncated=truncated,
    )


_UNKNOWN_LANGUAGES = {"", "und", "unk", "unknown", "undefined", "none", "null"}
_GENERIC_TITLES = {"", "audio", "subtitle", "subtitles", "track", "unknown", "undefined", "und"}


def _discover_stream_issues(
    db: Path, *, limit: int, include_stream_fixes: bool, include_ocr: bool
) -> tuple[list[MediaLibraryFixIssue], set[int], bool]:
    query = """
        WITH typed AS (
            SELECT
                s.*,
                mi.path, mi.title AS media_title, mi.filename, mi.item_type, mi.duration_s AS media_duration,
                mi.nfo_path,
                CASE
                    WHEN lower(trim(coalesce(s.stream_type, '')))='audio' OR coalesce(s.channels, 0) > 0 THEN 'audio'
                    WHEN lower(trim(coalesce(s.stream_type, ''))) IN ('subtitle', 'subtitles', '2') THEN 'subtitle'
                    ELSE ''
                END AS normalized_type
            FROM media_streams s
            JOIN media_items mi ON mi.id=s.media_id
            WHERE mi.active=1 AND mi.exists_flag=1
              AND lower(coalesce(mi.item_type, '')) IN ('movie', 'episode', 'video')
              AND lower(coalesce(s.source_kind, 'internal'))='internal'
              AND lower(mi.path) LIKE '%.mkv'
        ), ordered AS (
            SELECT typed.*,
                   row_number() OVER (
                       PARTITION BY media_id, normalized_type
                       ORDER BY coalesce(stream_index, 2147483647), id
                   ) AS type_ordinal
            FROM typed
            WHERE normalized_type IN ('audio', 'subtitle')
        )
        SELECT * FROM ordered
         WHERE (? = 1 AND (
                   lower(trim(coalesce(language, ''))) IN ('', 'und', 'unk', 'unknown', 'undefined', 'none', 'null')
                OR lower(trim(coalesce(title, ''))) IN ('', 'audio', 'subtitle', 'subtitles', 'track', 'unknown', 'undefined', 'und')
               ))
            OR (? = 1 AND normalized_type='subtitle' AND lower(trim(coalesce(codec, ''))) IN (
                'hdmv_pgs_subtitle', 'pgs', 'dvd_subtitle', 'vobsub'
            ))
         ORDER BY media_id, normalized_type, type_ordinal
         LIMIT ?
    """
    with closing(_connect(db)) as conn:
        rows = conn.execute(
            query,
            (1 if include_stream_fixes else 0, 1 if include_ocr else 0, max(2, limit * 4) + 1),
        ).fetchall()
    truncated = len(rows) > max(2, limit * 4)
    issues: list[MediaLibraryFixIssue] = []
    media_ids: set[int] = set()
    for row in rows[: max(2, limit * 4)]:
        media_id = int(row["media_id"])
        media_ids.add(media_id)
        language = str(row["language"] or "").strip().casefold()
        title = str(row["title"] or "").strip()
        base = dict(
            media_id=media_id,
            path=str(row["path"] or ""),
            title=str(row["media_title"] or row["filename"] or ""),
            item_type=str(row["item_type"] or "video"),
            stream_id=int(row["id"]),
            stream_index=int(row["stream_index"]) if row["stream_index"] is not None else None,
            stream_type=str(row["normalized_type"] or ""),
            stream_ordinal=int(row["type_ordinal"]),
            codec=str(row["codec"] or ""),
            language=str(row["language"] or ""),
            track_title=title,
            forced=bool(row["forced"]),
            channels=int(row["channels"]) if row["channels"] is not None else None,
            bitrate=int(row["bitrate"]) if row["bitrate"] is not None else None,
            duration_s=float(row["media_duration"] or 0) or None,
            source_kind=str(row["source_kind"] or "internal"),
            external_path=str(row["external_path"] or ""),
            nfo_path=str(row["nfo_path"] or ""),
        )
        codec = str(base["codec"] or "").casefold()
        bitmap = base["stream_type"] == "subtitle" and codec in {
            "hdmv_pgs_subtitle", "pgs", "dvd_subtitle", "vobsub"
        }
        if include_ocr and bitmap:
            issues.append(MediaLibraryFixIssue(
                **base,
                issue_type="bitmap_subtitle_ocr",
                action=ACTION_OCR_BITMAP_SUBTITLE,
                problem="Bilduntertitel kann per OCR in SRT umgewandelt werden",
                action_label="OCR-Entwurf erzeugen",
                detail=f"Subtitle {base['stream_ordinal']} · {base['codec'] or '?'} · Original bleibt erhalten",
            ))
        if include_stream_fixes and language in _UNKNOWN_LANGUAGES and not bitmap:
            label = "Audio-Sprache erkennen" if base["stream_type"] == "audio" else "Untertitel-Sprache erkennen"
            issues.append(MediaLibraryFixIssue(
                **base,
                issue_type="stream_language_unknown",
                action=ACTION_DETECT_STREAM_LANGUAGE,
                problem=f"{base['stream_type'].title()}-Sprache unbekannt",
                action_label=label,
                detail=f"Track {base['stream_ordinal']} · {base['codec'] or '?'}",
            ))
        elif include_stream_fixes and title.casefold() in _GENERIC_TITLES and language not in _UNKNOWN_LANGUAGES:
            issues.append(MediaLibraryFixIssue(
                **base,
                issue_type="track_title_missing",
                action=ACTION_FIX_TRACK_TITLE,
                problem="Tracktitel fehlt/ist generisch",
                action_label="Tracktitel ergänzen",
                detail=f"{base['stream_type'].title()} {base['stream_ordinal']} · {base['language']}",
            ))
    return issues, media_ids, truncated


def _issues_from_row(row, categories: set[str]) -> list[MediaLibraryFixIssue]:
    base = {
        "media_id": int(row["id"]),
        "path": str(row["path"] or ""),
        "title": str(row["title"] or ""),
        "item_type": str(row["item_type"] or "video"),
    }
    issues: list[MediaLibraryFixIssue] = []
    if "nfo" in categories and str(row["nfo_status"] or "").casefold() == "missing":
        issues.append(
            MediaLibraryFixIssue(
                **base,
                issue_type="nfo_missing",
                action=ACTION_GENERATE_NFO,
                problem="NFO fehlt",
                action_label="NFO erzeugen",
            )
        )
    trickplay_status = str(row["trickplay_status"] or "").casefold()
    if "trickplay" in categories and trickplay_status in {"missing", "empty"}:
        issues.append(
            MediaLibraryFixIssue(
                **base,
                issue_type="trickplay_missing" if trickplay_status == "missing" else "trickplay_empty",
                action=ACTION_GENERATE_TRICKPLAY,
                problem="Trickplay fehlt" if trickplay_status == "missing" else "Trickplay ist leer",
                action_label="Trickplay erzeugen",
            )
        )

    metadata_reasons = _metadata_reasons(row) if "metadata" in categories else []
    if metadata_reasons:
        issues.append(
            MediaLibraryFixIssue(
                **base,
                issue_type="metadata_incomplete",
                action=ACTION_REANALYZE,
                problem="Medienanalyse unvollständig",
                action_label="Metadaten neu analysieren",
                detail=", ".join(metadata_reasons),
            )
        )
    return issues


def _metadata_reasons(row) -> list[str]:
    reasons: list[str] = []
    if not row["has_video"]:
        reasons.append("Videostream fehlt")
    if not row["has_audio"]:
        reasons.append("Audiostream fehlt")
    if not str(row["video_codec"] or "").strip():
        reasons.append("Videocodec unbekannt")
    if int(row["width"] or 0) <= 0 and int(row["height"] or 0) <= 0:
        reasons.append("Auflösung unbekannt")
    try:
        duration = float(row["duration_s"] or 0)
    except (TypeError, ValueError):
        duration = 0
    if duration <= 0:
        reasons.append("Dauer unbekannt")
    return reasons


def dedupe_fix_issues(issues: Iterable[MediaLibraryFixIssue]) -> list[MediaLibraryFixIssue]:
    result: list[MediaLibraryFixIssue] = []
    seen: set[str] = set()
    for issue in issues:
        if issue.key in seen:
            continue
        seen.add(issue.key)
        result.append(issue)
    return result


def refresh_sidecar_statuses(db_path: str | Path, media_path: str | Path) -> bool:
    """Refresh NFO/trickplay status without re-analysing the video stream."""
    db = initialize_database_once(db_path)
    path = str(Path(media_path))
    nfo_status = _nfo_status_for_path(path)
    trickplay_status = _trickplay_status_for_path(path)
    with closing(_connect(db)) as conn, conn:
        cursor = conn.execute(
            """
            UPDATE media_items
               SET nfo_status=?, trickplay_status=?, updated_at=?
             WHERE path=?
            """,
            (nfo_status, trickplay_status, _now(), path),
        )
        if cursor.rowcount:
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('updated_at', ?)",
                (_now(),),
            )
    return bool(cursor.rowcount)


__all__ = [
    "ACTION_GENERATE_NFO",
    "ACTION_GENERATE_TRICKPLAY",
    "ACTION_REANALYZE",
    "ACTION_DETECT_STREAM_LANGUAGE",
    "ACTION_FIX_TRACK_TITLE",
    "ACTION_OCR_BITMAP_SUBTITLE",
    "MediaLibraryFixDiscoveryResult",
    "MediaLibraryFixIssue",
    "MediaLibraryFixOutcome",
    "dedupe_fix_issues",
    "discover_fix_issues",
    "refresh_sidecar_statuses",
]
