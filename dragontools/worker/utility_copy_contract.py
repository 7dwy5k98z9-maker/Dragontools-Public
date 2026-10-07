"""Build preservation proof from an owned source probe and media analysis."""
from pathlib import Path

from ..core.lang_codes import canonical_lang
from ..core.media_metadata import normalize_video_codec
from ..core.process_runner import subprocess_no_window_kwargs
from ..core.media_analyzer import analyze_media
from ..core.media_hdr_detection import detect_hdr_from_ffprobe_stream
from .media_contract import _audio_codec_family, _subtitle_codec_family
from .media_contract_types import ExpectedMediaContract, ExpectedAudioTrack, ExpectedSubtitleTrack
from .output_contract_verifier import video_bit_depth
from .output_probe import probe_output
from .owned_probe import owned_probe_runner
from .utility_media_analysis import analyze_owned_media


def copied_audio_track(stream):
    tags = stream.get('tags') or {}
    disposition = stream.get('disposition') or {}
    return ExpectedAudioTrack(codec=_audio_codec_family(stream.get('codec_name')),
        channels=int(stream.get('channels') or 0), language=canonical_lang(tags.get('language')),
        default=bool(disposition.get('default')), forced=bool(disposition.get('forced')),
        title=str(tags.get('title') or ''))


def copied_subtitle_track(stream):
    tags = stream.get('tags') or {}
    disposition = stream.get('disposition') or {}
    return ExpectedSubtitleTrack(codec=_subtitle_codec_family(stream.get('codec_name')),
        language=canonical_lang(tags.get('language')), default=bool(disposition.get('default')),
        forced=bool(disposition.get('forced')), title=str(tags.get('title') or ''))


def copy_video_requirements(video, media):
    hdr, hdrplus, dv_profile = detect_hdr_from_ffprobe_stream(video)
    return dict(min_video_bit_depth=video_bit_depth(video),
        require_hdr=hdr or bool(getattr(media, 'is_hdr', False)),
        require_hdr10plus=hdrplus or bool(getattr(media, 'has_hdrplus', False)),
        require_dolby_vision=dv_profile is not None or bool(getattr(media, 'has_dv', False)),
        expected_dolby_vision_profile=(int(getattr(media, 'dv_profile_major', 0) or dv_profile or 0) or None),
        expected_width=int(video.get('width') or 0) or None,
        expected_height=int(video.get('height') or 0) or None)


def probe_copy_source(path, tools, worker):
    media = analyze_owned_media(path, tools, worker=worker, analyzer=analyze_media)
    probe = probe_output(Path(path), ffprobe_path=str(tools.ffprobe),
        run_process=owned_probe_runner(worker, label='ISO-Fallback Quellvertrag'),
        no_window_kwargs=subprocess_no_window_kwargs())
    if not probe.video_streams:
        raise RuntimeError('ISO-Fallback-Quelle besitzt keinen bestätigten Videostream.')
    primary = probe.video_streams[0]
    contract = ExpectedMediaContract(container='mkv',
        video_codec=normalize_video_codec(primary.get('codec_name')),
        video_stream_count=len(probe.video_streams),
        audio_tracks=tuple(copied_audio_track(stream) for stream in probe.audio_streams),
        subtitle_tracks=tuple(copied_subtitle_track(stream) for stream in probe.subtitle_streams),
        attachment_stream_count=sum(stream.get('codec_type') == 'attachment' for stream in probe.streams) + len(probe.attached_picture_streams),
        data_stream_count=sum(stream.get('codec_type') == 'data' for stream in probe.streams),
        **copy_video_requirements(primary, media))
    return contract, float(media.duration_s or probe.duration_s or 0), len(probe.chapters)
