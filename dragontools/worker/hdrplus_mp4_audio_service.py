"""Validate donor inventory and stage every MP4 audio track explicitly."""
import json
from pathlib import Path
from ..core.strict_numbers import nonnegative_integer
from .mp4box_track_args import mp4box_track_argument


class HDRPlusMP4AudioService:
    def __init__(self, tools, log, run_tool, capture_tool):
        self.tools = tools
        self.log = log
        self.run_tool = run_tool
        self.capture_tool = capture_tool

    def probe(self, donor):
        if not donor.is_file() or donor.stat().st_size < 128:
            return None
        result = self.capture_tool([
            getattr(self.tools, 'ffprobe', 'ffprobe'), '-v', 'error',
            '-select_streams', 'a', '-show_entries',
            'stream=index,codec_name:stream_tags=language,title:stream_disposition=default',
            '-of', 'json', str(donor),
        ], label='HDR10+: MP4-Audioanalyse', timeout_s=30)
        if not result.ok or getattr(result, 'aborted', False) or getattr(result, 'timed_out', False):
            self.log('❌ HDR10+ MP4: Audioanalyse des Stream-Donors fehlgeschlagen.', 'error')
            return None
        try:
            payload = json.loads(result.stdout)
            streams = payload['streams']
            if not isinstance(streams, list):
                raise ValueError('streams must be a list')
            ids = []
            for stream in streams:
                if not isinstance(stream, dict) or not stream.get('codec_name'):
                    raise ValueError('invalid audio stream')
                ids.append(nonnegative_integer(stream.get('index')))
                if not isinstance(stream.get('tags', {}), dict) or not isinstance(stream.get('disposition', {}), dict):
                    raise ValueError('invalid audio metadata')
            if len(ids) != len(set(ids)):
                raise ValueError('duplicate audio index')
            return streams
        except (ValueError, TypeError, KeyError) as exc:
            self.log(f'❌ HDR10+ MP4: Ungültige ffprobe-Audioanalyse: {exc}', 'error')
            return None

    @staticmethod
    def audio_ext(codec):
        return {'aac': '.m4a', 'ac3': '.ac3', 'eac3': '.eac3', 'mp3': '.mp3'}.get(str(codec or '').lower(), '.mka')

    def prepare_additions(self, donor, tmp_dir):
        streams = self.probe(donor)
        if streams is None:
            return None
        additions = []
        for ordinal, stream in enumerate(streams):
            audio = tmp_dir / f'mp4_audio_{ordinal}{self.audio_ext(stream["codec_name"])}'
            command = [self.tools.ffmpeg, '-y', '-loglevel', 'error', '-i', str(donor),
                       '-map', f'0:{nonnegative_integer(stream["index"])}', '-c:a', 'copy', str(audio)]
            if not self.run_tool(command, label=f'HDR10+: MP4-Audio #{ordinal} extrahieren', tool_name='ffmpeg'):
                return None
            if not audio.is_file() or audio.stat().st_size < 128:
                return None
            tags = stream.get('tags') or {}
            language = str(tags.get('language') or 'und').lower()
            title = str(tags.get('title') or '').replace('"', "'").strip()
            addition = mp4box_track_argument(audio, language=language, title=title,media_type='audio',
                default=stream.get('disposition',{}).get('default'))
            additions.extend(['-add', addition])
        return additions
