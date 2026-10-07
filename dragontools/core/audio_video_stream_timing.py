"""Translate selected audio packet timestamps onto the analyzed video origin."""
import math


def _timestamp(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('Non-finite stream timestamp')
    return result


def stream_timing(payload, video_index):
    streams = payload.get('streams') or []
    video = next((s for s in streams if s.get('codec_type') == 'video'
                  and s.get('index') == video_index), {})
    try:
        origin = _timestamp(video.get('start_time'))
    except (TypeError, ValueError):
        return 0.0, {}
    offsets = {}
    for stream in streams:
        if stream.get('codec_type') != 'audio':
            continue
        try:
            offsets[int(stream['index'])] = _timestamp(stream.get('start_time')) - origin
        except (KeyError, TypeError, ValueError):
            continue
    return origin, offsets


def selected_audio_timing(info, index):
    offsets = getattr(info, 'audio_start_offsets', None)
    if offsets is None:  # Legacy callers supply an already normalized model.
        return None, ''
    if index not in offsets:
        return None, 'Zeitlage der gewählten Audiospur konnte nicht zuverlässig bestimmt werden.'
    try:
        return _timestamp(offsets[index]), ''
    except (TypeError, ValueError):
        return None, 'Ungültige Zeitlage der gewählten Audiospur.'


def source_audio_timing_filter(offset_s):
    if offset_s is None:
        return []
    # Materialize the audio/video lead gap before trimming/resetting segment
    # timestamps. first_pts=0 also removes samples preceding the video origin.
    return [f'asetpts=PTS-STARTPTS+({offset_s:.9f})/TB', 'aresample=async=1:first_pts=0']
