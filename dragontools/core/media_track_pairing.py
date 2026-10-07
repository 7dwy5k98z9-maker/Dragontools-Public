"""Associate probe tracks without treating tool-specific IDs as stream indices."""
from __future__ import annotations

import re


def _container_id(value):
    text = '' if value is None or isinstance(value, bool) else str(value).strip()
    if not re.fullmatch(r'(?:[0-9]+|0[xX][0-9a-fA-F]+)', text):
        return None
    return int(text, 16 if text.lower().startswith('0x') else 10)


def _codec(track, *, probe=False):
    value = str(track.get('codec_name' if probe else 'Format') or '').strip().casefold()
    aliases = {'h265':'hevc', 'avc':'h264', 'e-ac-3':'eac3', 'ac-3':'ac3',
               'utf-8':'subrip', 'srt':'subrip', 'pgs':'hdmv_pgs_subtitle',
               'vobsub':'dvd_subtitle', 'advanced substation alpha':'ass',
               'substation alpha':'ssa', 'mpeg audio':'mp3'}
    return aliases.get(value, value)


def _compatible(track, stream):
    left, right = _codec(track), _codec(stream, probe=True)
    return not left or not right or left == right


def _matching_track(tracks, stream, ordinal, *, positional):
    stream_id = _container_id(stream.get('id'))
    identified = [(n,t) for n,t in tracks if _container_id(t.get('ID')) is not None]
    if stream_id is not None and identified:
        matches = [(n,t) for n,t in identified if _container_id(t.get('ID')) == stream_id]
        return matches[0] if len(matches) == 1 and _compatible(matches[0][1], stream) else None
    compatible = [(n,t) for n,t in tracks if _compatible(t,stream)]
    if len(compatible) == 1:
        return compatible[0]
    if positional:
        return next(((n,t) for n,t in compatible if n == ordinal), None)
    return None


def pair_media_tracks(media_tracks, probe_streams, warnings=None):
    """ffprobe owns topology; MI enriches only associated existing streams.

    Container IDs may be compared with each other, never with ffprobe index or
    MediaInfo StreamOrder. Equal-count ordinal fallback is used only without
    shared identity evidence and with compatible codecs. Ambiguous unmatched
    tracks are kept as probe-only data instead of inheriting foreign metadata.
    """
    if not probe_streams:
        return [(track,{}) for track in media_tracks]
    available = list(enumerate(media_tracks))
    pairs = []
    for ordinal,stream in enumerate(probe_streams):
        selected = _matching_track(available,stream,ordinal,positional=len(media_tracks)==len(probe_streams))
        if selected is None:
            pairs.append(({},stream))
        else:
            available.remove(selected)
            pairs.append((selected[1],stream))
    if available and warnings is not None:
        message = '[Track-Zuordnung] Nicht zugeordnete MediaInfo-Spuren werden nicht in die ffprobe-Topologie übernommen.'
        if message not in warnings:
            warnings.append(message)
    return pairs
