"""Preserved-target expectations use the shared media-contract verifier."""
from types import SimpleNamespace

from ..core.media_hdr_detection import detect_hdr_from_ffprobe_stream, parse_dolby_vision_from_ffprobe_stream
from .media_contract import _audio_codec_family, _subtitle_codec_family
from .media_contract_types import ExpectedAudioTrack, ExpectedSubtitleTrack, ExpectedMediaContract
from .output_contract_tracks import compare_audio_tracks, compare_subtitle_tracks
from .output_contract_metadata import verify_dynamic_metadata_contract


def _metadata(video, media):
    hdr, hdrplus, _ = detect_hdr_from_ffprobe_stream(video)
    dv = parse_dolby_vision_from_ffprobe_stream(video)
    return SimpleNamespace(
        has_hdr=hdr or bool(getattr(media, 'is_hdr', False)),
        has_dolby_vision=dv['dolby_vision'] or bool(getattr(media, 'has_dv', False)),
        has_hdr10plus=hdrplus or bool(getattr(media, 'has_hdrplus', False)),
        dolby_vision_profile=dv['dv_profile_major'] or getattr(media, 'dv_profile_major', None))


def _copied_audio(stream):
    tags, flags = stream.get('tags') or {}, stream.get('disposition') or {}
    return ExpectedAudioTrack(_audio_codec_family(stream.get('codec_name')), int(stream.get('channels') or 0),
        tags.get('language') or 'und', default=False, title=tags.get('title') or '', forced=bool(flags.get('forced')))


def _copied_subtitle(stream):
    tags, flags = stream.get('tags') or {}, stream.get('disposition') or {}
    return ExpectedSubtitleTrack(_subtitle_codec_family(stream.get('codec_name')), tags.get('language') or 'und',
        forced=bool(flags.get('forced')), default=bool(flags.get('default')), title=tags.get('title') or '')


def require_preserved_target(output, target, plan, channels, *, output_media=None, target_media=None):
    out_video, target_video = output.video_streams[0], target.video_streams[0]
    for key in ('codec_name', 'width', 'height', 'pix_fmt', 'color_transfer', 'color_primaries'):
        if out_video.get(key) != target_video.get(key):
            raise RuntimeError(f"Zielvideo wurde nicht unverändert übernommen: {key}.")
    metadata = _metadata(target_video, target_media)
    contract = ExpectedMediaContract('mkv', str(target_video.get('codec_name') or ''), 1,
        (ExpectedAudioTrack(_audio_codec_family(plan.target_codec), channels or 0,
            plan.target_language or 'und', default=True, forced=False),
         *(_copied_audio(s) for s in target.audio_streams)),
        tuple(_copied_subtitle(s) for s in target.subtitle_streams),
        require_hdr=metadata.has_hdr, require_dolby_vision=metadata.has_dolby_vision,
        expected_dolby_vision_profile=metadata.dolby_vision_profile, require_hdr10plus=metadata.has_hdr10plus)
    messages = (compare_audio_tracks(contract, output.audio_streams)
        + compare_subtitle_tracks(contract, output.subtitle_streams)
        + verify_dynamic_metadata_contract(_metadata(out_video, output_media), contract))
    if messages:
        raise RuntimeError(' '.join(messages))
    other = lambda probe: [(s.get('codec_type'), s.get('codec_name')) for s in probe.streams
                           if s.get('codec_type') not in {'video', 'audio', 'subtitle'}]
    if other(output) != other(target) or output.chapters != target.chapters:
        raise RuntimeError("Anhänge, Datenspuren oder Kapitel wurden nicht vollständig erhalten.")
