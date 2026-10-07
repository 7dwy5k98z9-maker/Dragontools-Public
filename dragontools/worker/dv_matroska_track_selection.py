"""Keep FFmpeg video ordinals and Matroska TrackNumbers at an explicit boundary."""
from __future__ import annotations

from ..core.media_stream_selection import primary_ffmpeg_video_index
from ..core.strict_numbers import nonnegative_integer, positive_integer


def _video_tracks(payload) -> list[dict]:
    raw = payload.get('tracks') if isinstance(payload, dict) else None
    if not isinstance(raw, list) or not all(isinstance(t, dict) for t in raw):
        raise ValueError('mkvmerge -J enthält keine gültige Trackliste')
    tracks = [t for t in raw if str(t.get('type', '')).casefold() == 'video']
    if not tracks:
        raise ValueError('mkvmerge meldet keine Videospur für die DV-Quelle')
    return tracks


def _primary_ordinal(media_info, tracks) -> int:
    videos = list(getattr(media_info, 'video_streams', []) or [])
    if not videos and len(tracks) == 1:
        return 0
    if len(videos) != len(tracks):
        raise ValueError('FFmpeg- und Matroska-Videospuranzahl widersprechen sich; keine TrackNumber wird geraten')
    primary = primary_ffmpeg_video_index(media_info)
    matches = []
    for ordinal, video in enumerate(videos):
        try:
            index = nonnegative_integer(getattr(video, 'index', None))
        except ValueError:
            raise ValueError('Ungültiger FFmpeg-Videostreamindex für DV-Trackauflösung') from None
        if index == primary:
            matches.append(ordinal)
    if len(matches) != 1:
        raise ValueError('Primäre FFmpeg-Videospur ist für die Matroska-Zuordnung nicht eindeutig')
    return matches[0]


def select_matroska_video_track_number(payload, media_info) -> int:
    tracks = _video_tracks(payload)
    ordinal = _primary_ordinal(media_info, tracks)
    try:
        numbers = [positive_integer(t['properties']['number']) for t in tracks]
    except (KeyError, TypeError, ValueError):
        raise ValueError('mkvmerge liefert keine gültige Matroska TrackNumber (properties.number)') from None
    if len(numbers) != len(set(numbers)):
        raise ValueError('Matroska TrackNumbers sind nicht eindeutig')
    return numbers[ordinal]
