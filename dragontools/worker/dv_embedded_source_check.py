"""Validate decoded DV metadata for HEVC/AV1 sources before AV1 encoding."""
from __future__ import annotations
import json
from .dv_source_rpu_check import SourceRpuSanityCheck, SOURCE_RPU_STAGE
from .dv_encode_command import primary_ffmpeg_video_index
from .frame_count_evidence import StreamIdentity
from .tool_runner import run_tool
from .dv_pipeline_timeouts import timeout_hevc_extract
from ..core.strict_numbers import positive_integer, nonnegative_integer

def validate_embedded_source(request, *, tools, temp_state, log, worker=None):
    check=SourceRpuSanityCheck(tools=tools,temp_state=temp_state,log=log)
    identity=StreamIdentity.capture(request.input_path)
    index=primary_ffmpeg_video_index(request.media_info)
    if index is None:
        return check.reject('Primäre DV-Quellvideospur ist nicht eindeutig.')
    def capture(command):
        return run_tool(command,label=SOURCE_RPU_STAGE,timeout_s=timeout_hevc_extract(),
                        worker=worker,log=log,abort_on_request=True)
    frames=capture([tools.ffprobe,'-v','error','-select_streams',str(index),'-count_frames',
                    '-show_entries','stream=index,codec_type,nb_read_frames','-of','json',request.input_path])
    if not frames.ok or frames.aborted or frames.timed_out or frames.stderr.strip():
        return check.reject('DV-Quellframes nicht zuverlässig lesbar; keine Metadatenfreigabe.')
    try:
        streams=json.loads(frames.stdout)['streams']
        if len(streams)!=1 or nonnegative_integer(streams[0]['index'])!=index or streams[0]['codec_type']!='video':
            raise ValueError('Falsche Quellspur')
        count=positive_integer(streams[0]['nb_read_frames'])
    except (ValueError,KeyError,TypeError) as exc:
        return check.reject(f'DV-Quellframezahl nicht eindeutig: {exc}')
    # Select parsed metadata, not just a raw RPU buffer. Passthrough prevents
    # VFR timestamps or gaps from creating duplicate frames in this count.
    metadata=capture([tools.ffmpeg,'-v','error','-nostdin','-i',request.input_path,
        '-map',f'0:{index}','-an','-sn','-dn','-vf',
        'sidedata=mode=select:type=DOVI_RPU_BUFFER,sidedata=mode=select:type=DOVI_METADATA',
        '-fps_mode','passthrough','-progress','pipe:1','-nostats','-f','null','-'])
    if not metadata.ok or metadata.aborted or metadata.timed_out or metadata.stderr.strip():
        return check.reject('DV-Metadatenprüfung fehlgeschlagen; Tool-/Decoderfehler bleiben sichtbar.')
    rows=dict(line.split('=',1) for line in metadata.stdout.splitlines() if '=' in line)
    try:
        if rows.get('progress')!='end':
            raise ValueError('Keine vollständige Zählung')
        rpu_count=nonnegative_integer(rows['frame'].strip())
    except (ValueError,KeyError) as exc:
        return check.reject(f'DV-Metadatenzahl nicht eindeutig: {exc}')
    if not identity.matches(request.input_path):
        return check.reject('DV-Quelle wurde während der Prüfung verändert.')
    return check.validate_counts(count,rpu_count)
