"""Build independent lossless timestamp attempts without executing commits."""
from uuid import uuid4
from ..core.process_runner import tool_available
from .duration_repair_commands import build_timestamp_repair_command, build_genpts_repair_command
from .duration_timestamp_helpers import mkv_video_track_id


def build_repair_attempts(out, before, container, runtime, supports_setts):
    kind = str(container or '').strip().lower().lstrip('.')
    attempts = []
    if kind == 'mp4':
        target = out.with_name(f'{out.stem}.timestamp_fix_{uuid4().hex}{out.suffix}')
        command = build_timestamp_repair_command(out, target, before.frame_rate,
            container=container, mp4box_path=runtime.mp4box_path, ffmpeg_path=runtime.ffmpeg_path)
        return [(target, command, 'MP4Box-Timestamp-Reparatur', 'MP4Box CFR-Neuaufbau')]
    if tool_available(runtime.mkvmerge_path):
        try:
            track_id = mkv_video_track_id(runtime, out)
            target = out.with_name(f'{out.stem}.timestamp_mkvmerge_{uuid4().hex}{out.suffix}')
            command = build_timestamp_repair_command(out, target, before.frame_rate,
                container=container, mp4box_path=runtime.mp4box_path, ffmpeg_path=runtime.ffmpeg_path,
                mkvmerge_path=runtime.mkvmerge_path, mkv_video_track_id=track_id)
            attempts.append((target, command, 'MKVToolNix-default-duration-Timestamp-Reparatur',
                             'MKVToolNix --default-duration'))
        except Exception as exc:
            runtime.log(f'⚠️ MKVToolNix-Videotrack-ID konnte nicht bestimmt werden: {exc}', 'warn')
    if tool_available(runtime.ffmpeg_path):
        if supports_setts():
            target = out.with_name(f'{out.stem}.timestamp_setts_{uuid4().hex}{out.suffix}')
            command = build_timestamp_repair_command(out, target, before.frame_rate,
                container=container, mp4box_path=runtime.mp4box_path, ffmpeg_path=runtime.ffmpeg_path)
            attempts.append((target, command, 'FFmpeg-setts-Timestamp-Reparatur', 'FFmpeg setts'))
        target = out.with_name(f'{out.stem}.timestamp_genpts_{uuid4().hex}{out.suffix}')
        attempts.append((target, build_genpts_repair_command(out, target, ffmpeg_path=runtime.ffmpeg_path),
            'FFmpeg-+genpts+igndts-Timestamp-Reparatur', 'FFmpeg +genpts+igndts'))
    return attempts
