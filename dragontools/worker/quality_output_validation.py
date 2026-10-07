"""Semantic gates for a video-only quality encode and an AV mux output."""
import math
from ..core.codec_utils import normalize_target_codec


def finite_duration(value):
    duration = float(value or 0)
    if not math.isfinite(duration) or duration <= 0:
        raise RuntimeError("Laufzeit der Ausgabe konnte nicht validiert werden.")
    return duration


def quality_video(probe, run):
    streams = probe.get('streams') or []
    videos = [s for s in streams if s.get('codec_type') == 'video'
              and not (s.get('disposition') or {}).get('attached_pic')]
    if not videos:
        raise RuntimeError("Testencode enthält laut ffprobe keine Videospur.")
    if len(videos) != 1 or len(streams) != 1:
        raise RuntimeError("Testencode enthält unerwartete weitere Spuren.")
    video = videos[0]
    if normalize_target_codec(video.get('codec_name'), strict=False) != normalize_target_codec(run.codec):
        raise RuntimeError("Videocodec des Testencodes entspricht nicht dem gewählten Lauf.")
    if int(video.get('width') or 0) <= 0 or int(video.get('height') or 0) <= 0:
        raise RuntimeError("Videodimensionen des Testencodes sind ungültig.")
    return video


def require_av_streams(info):
    if len(info.video_streams) != 1 or info.attached_picture_streams:
        raise RuntimeError("Matcher-Ausgabe enthält keine eindeutige Videospur.")
    if not info.audio_streams:
        raise RuntimeError("Matcher-Ausgabe enthält keine synchronisierte Audiospur.")
    if 'matroska' not in info.format_name.split(','):
        raise RuntimeError("Matcher-Ausgabe ist kein Matroska-Container.")
