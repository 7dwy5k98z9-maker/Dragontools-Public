"""Validate source stream identity and adapt extraction callbacks before calls."""
import inspect
from ..core.media_stream_selection import primary_ffmpeg_video_index


def trusted_hdr_primary_index(media_info):
    index = primary_ffmpeg_video_index(media_info)
    primary = getattr(media_info, 'primary_video', None)
    declared = getattr(media_info, 'video_streams', None) is not None or hasattr(primary, 'index')
    if getattr(media_info, 'ffmpeg_stream_indices_trusted', True) is False or (declared and index is None):
        raise ValueError('Primäre FFmpeg-Videospur ist nicht zuverlässig zugeordnet.')
    return index


def extract_selected_hdr_video(callback, source, target, index):
    try:
        signature = inspect.signature(callback)
    except (TypeError, ValueError):
        # An opaque modern callback gets the explicit contract exactly once.
        return callback(source, target, stream_index=index)
    try:
        signature.bind(source, target, stream_index=index)
    except TypeError:
        if index not in (None, 0):
            return False
        return callback(source, target)
    return callback(source, target, stream_index=index)
