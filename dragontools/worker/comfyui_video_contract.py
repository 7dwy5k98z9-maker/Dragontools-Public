"""Validate actual video bytes before handing an external HDR result to the mux."""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

from ..core.comfyui_timing import positive_fps
from ..core.strict_numbers import positive_integer
from ..core.timeout_settings import get_timeout
from .tool_runner import run_tool


@dataclass(frozen=True, slots=True)
class VideoEvidence:
    success: bool
    message: str = ''
    video_offset_s: float = 0.0
    source_input_offset_s: float = 0.0
    source_audio_count: int = 0
    source_subtitle_count: int = 0


def _probe(tools, path, worker, log):
    command = [str(getattr(tools, 'ffprobe', '') or 'ffprobe'), '-v', 'error',
        '-count_frames', '-show_streams', '-show_format', '-of', 'json', str(path)]
    result = run_tool(command, label='ComfyUI: Videoprüfung', timeout_s=get_timeout('worker_media_process'),
        timeout_mode='inactivity', worker=worker, log=log, abort_on_request=True)
    if result.returncode != 0 or result.aborted or result.timed_out:
        raise ValueError(result.stderr or 'ffprobe konnte die Videodatei nicht vollständig prüfen.')
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict) or not isinstance(payload.get('streams'), list):
        raise ValueError('ffprobe liefert kein Streaminventar.')
    return payload


def _count(stream):
    return positive_integer(stream.get('nb_read_frames'))


def _rate(stream, fps):
    actual = positive_fps(stream.get('avg_frame_rate')) or positive_fps(stream.get('r_frame_rate'))
    if actual is None or abs(float(actual - fps)) > 0.001:
        raise ValueError('Die tatsächliche Framerate stimmt nicht mit der CFR-Quelle überein.')


def _encoder_codec(encode_args):
    for pos, item in enumerate(encode_args[:-1]):
        if item in {'-c:v', '-codec:v'}:
            name = str(encode_args[pos + 1]).lower()
            if 'av1' in name: return 'av1'
            if '265' in name or 'hevc' in name: return 'hevc'
    raise ValueError('ComfyUI benötigt einen geplanten HEVC- oder AV1-Encoder.')


def _timestamp(value):
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError('Ungültiger Quellzeitstempel.')
    return parsed


def _validate_hdr_video(video, fps, frames, encode_args):
    if video.get('codec_name') != _encoder_codec(encode_args):
        raise ValueError('Der tatsächliche Videocodec entspricht nicht dem Encoderplan.')
    if (video.get('color_primaries'), video.get('color_transfer'), video.get('color_space')) != ('bt2020', 'smpte2084', 'bt2020nc'):
        raise ValueError('ComfyUI-Ausgabe ist kein eindeutig getaggtes BT.2020/PQ-Video.')
    if not re.search(r'(?:p|p0)(?:10|12|16)(?:le|be)', str(video.get('pix_fmt') or '')):
        raise ValueError('ComfyUI-Ausgabe hat keine nachgewiesenen mindestens 10 Bit.')
    if _count(video) != frames:
        raise ValueError('Die tatsächliche Ausgabe-Framezahl stimmt nicht mit dem Manifest überein.')
    _rate(video, fps)


def verify_comfyui_video(*, tools, worker, log, input_path, output_path, source_index, fps, frames, encode_args):
    try:
        output = _probe(tools, output_path, worker, log)
        streams = output['streams']
        if len(streams) != 1 or streams[0].get('codec_type') != 'video':
            raise ValueError('ComfyUI muss genau einen Video-Stream ohne Audio/Untertitel erzeugen.')
        video = streams[0]
        _validate_hdr_video(video, fps, frames, encode_args)
        source = _probe(tools, input_path, worker, log)
        selected = [s for s in source['streams'] if s.get('index') == source_index and s.get('codec_type') == 'video']
        if len(selected) != 1 or _count(selected[0]) != frames:
            raise ValueError('Quelle und HDR-Ausgabe haben keine identische nachgewiesene Framezahl.')
        _rate(selected[0], fps)
        source_start = _timestamp(source.get('format', {}).get('start_time', 0.0))
        video_start = _timestamp(selected[0].get('start_time', source_start))
        output_start = _timestamp(video.get('start_time', 0.0))
        return VideoEvidence(True, video_offset_s=video_start - source_start - output_start,
            source_input_offset_s=-source_start,
            source_audio_count=sum(s.get('codec_type') == 'audio' for s in source['streams']),
            source_subtitle_count=sum(s.get('codec_type') == 'subtitle' for s in source['streams']))
    except (OSError, ValueError, TypeError, KeyError, OverflowError) as exc:
        return VideoEvidence(False, message=str(exc))


def _planned_count(args, kind, all_count):
    disabled = '-an' if kind == 'audio' else '-sn'
    if disabled in args: return 0
    generic = '0:a' if kind == 'audio' else '0:s'
    selectors = [str(args[pos + 1]).rstrip('?') for pos, item in enumerate(args[:-1]) if item == '-map']
    return sum(all_count if selector == generic else 1 for selector in selectors)


def verify_comfyui_mux(*, tools, worker, log, output_path, container, fps, rendered, encode_args, audio_args, subtitle_args):
    try:
        payload = _probe(tools, output_path, worker, log)
        streams = payload['streams']
        videos = [s for s in streams if s.get('codec_type') == 'video']
        if len(videos) != 1:
            raise ValueError('Finaler ComfyUI-Mux enthält nicht genau ein Video.')
        _validate_hdr_video(videos[0], fps, rendered.frames, encode_args)
        actual_format = set(str(payload.get('format', {}).get('format_name') or '').split(','))
        expected_format = 'matroska' if container.lower() == 'mkv' else 'mov'
        if expected_format not in actual_format:
            raise ValueError('Tatsächlicher Ausgabecontainer entspricht nicht dem geplanten Ziel.')
        for kind, args, source_count in (
            ('audio', audio_args, getattr(rendered, 'source_audio_count', 0)),
            ('subtitle', subtitle_args, getattr(rendered, 'source_subtitle_count', 0)),
        ):
            if sum(s.get('codec_type') == kind for s in streams) != _planned_count(args, kind, source_count):
                raise ValueError(f'Finaler ComfyUI-Mux verletzt die geplante Anzahl {kind}.')
        return VideoEvidence(True)
    except (OSError, ValueError, TypeError, KeyError, OverflowError) as exc:
        return VideoEvidence(False, message=str(exc))


def validate_job_paths(input_path, output_path, manifest_path):
    from .hdr_metadata_file_ownership import metadata_output_conflicts_with_sources
    paths = [str(input_path), str(output_path), str(manifest_path), str(manifest_path) + '.cancel']
    if any(not p.strip() for p in paths):
        raise ValueError('Quelle, Ausgabe und Manifest müssen unterschiedliche Dateipfade besitzen.')
    for pos, path in enumerate(paths):
        if metadata_output_conflicts_with_sources(path, *paths[:pos]):
            raise ValueError('Path collision: Quelle, Ausgabe und Manifest müssen unterschiedliche Dateien sein.')
