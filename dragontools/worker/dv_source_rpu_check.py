"""Fast plausibility check of source RPU length before Dolby-Vision encoding."""
from __future__ import annotations
import json
from fractions import Fraction
from .dv_encode_command import primary_ffmpeg_video_index
from .frame_count_evidence import StreamIdentity
from .dv_pipeline_timeouts import timeout_hevc_extract
from ..core.strict_numbers import nonnegative_integer, positive_integer

SOURCE_RPU_STAGE = 'DV SOURCE-RPU-CHECK'
UNUSABLE_RPU_PREFIX = 'SOURCE_RPU_UNUSABLE:'

class SourceRpuSanityCheck:
    def __init__(self, *, tools, temp_state, log):
        self.tools, self.temp_state, self.log = tools, temp_state, log

    def reject(self, reason, *, unusable=False):
        message = (UNUSABLE_RPU_PREFIX+' ' if unusable else '')+reason
        self.temp_state.record_failure(reason=message,stage=SOURCE_RPU_STAGE)
        self.log('[DV][SOURCE-RPU-CHECK] '+message,'error')
        return False

    def validate(self, state, runner, *, probe_rpu):
        req=state.request
        identity=StreamIdentity.capture(req.input_path)
        rpu_identity=StreamIdentity.capture(state.files.rpu_orig)
        rpu_count=probe_rpu(runner,state.files.rpu_orig)
        if rpu_count is None:
            return self.reject('Quell-RPU kann nicht vollständig gelesen/gezählt werden; keine DV-Freigabe.')
        try:
            rpu_count=nonnegative_integer(rpu_count)
            video_count, evidence=self._video_frame_estimate(req,runner)
        except (KeyError,TypeError,ValueError) as exc:
            return self.reject(f'Quell-RPU-Plausibilitätsprüfung unvollständig: {exc}')
        if not identity.matches(req.input_path) or not rpu_identity.matches(state.files.rpu_orig):
            return self.reject('Quelle/RPU wurde während der Prüfung verändert; Ergebnis verworfen.')
        if rpu_count==0:
            return self.reject('Quell-RPU enthält keine Frames.',unusable=True)
        if video_count is None:
            self.log('[DV][SOURCE-RPU-CHECK] Keine brauchbare Quell-Framezahl in den Metadaten; '
                'RPU ist lesbar. Exakter Abgleich erfolgt nach dem Encode.','warn')
            return True
        self.log(f'[DV][SOURCE-RPU-CHECK] Schneller Plausibilitätsvergleich ({evidence}); '
            'keine vollständige Quellvideozählung.','info')
        return self.validate_counts(video_count,rpu_count,plausibility=True)

    def _video_frame_estimate(self, request, runner):
        media=request.media_info
        index=primary_ffmpeg_video_index(media)
        if index is None:
            raise ValueError('Primäre Quellvideospur ist nicht eindeutig.')
        video=media.primary_video
        count=_positive_count(getattr(video,'frame_count',None))
        if count is not None:
            return count,'analysierte Videospur-Metadaten'
        proc=runner.run([self.tools.ffprobe,'-v','error','-select_streams',str(index),
            '-show_entries','stream=index,codec_type,nb_frames,duration,avg_frame_rate,r_frame_rate:'
            'stream_tags=NUMBER_OF_FRAMES,DURATION:format=duration','-of','json',request.input_path],
            return_process=True,timeout=min(60,timeout_hevc_extract()),label=SOURCE_RPU_STAGE)
        if proc is None or getattr(proc,'returncode',1)!=0 or getattr(proc,'aborted',False) or getattr(proc,'timed_out',False) or str(getattr(proc,'stderr','') or '').strip():
            raise ValueError('Quellvideometadaten nicht zuverlässig lesbar oder Prüfung abgebrochen.')
        payload=json.loads(proc.stdout)
        streams=payload['streams']
        if len(streams)!=1 or nonnegative_integer(streams[0]['index'])!=index or streams[0]['codec_type']!='video':
            raise ValueError('Falsche oder mehrdeutige Quellvideospur')
        stream=streams[0]
        tags=stream.get('tags') or {}
        count=_positive_count(stream.get('nb_frames'),tags.get('NUMBER_OF_FRAMES'))
        if count is not None:
            return count,'Container-Framezahl'
        if str(getattr(video,'frame_rate_mode','') or '').upper() in {'VFR','VARIABLE'}:
            return None,'variable Bildrate ohne Framezahl'
        duration=_positive_fraction(stream.get('duration'),tags.get('DURATION'),
            getattr(video,'duration_s',None),getattr(media,'duration_s',None),
            (payload.get('format') or {}).get('duration'))
        fps=_positive_fraction(stream.get('avg_frame_rate'),getattr(video,'frame_rate',None),
            stream.get('r_frame_rate'))
        if duration is None or fps is None:
            return None,'Dauer/Bildrate unbekannt'
        return max(1,round(duration*fps)),'Schätzung aus Videodauer × Bildrate'

    def validate_counts(self, video_count, rpu_count, *, plausibility=False):
        self.log(f'[DV][SOURCE-RPU-CHECK] Video Frames: {video_count}; RPU Frames: {rpu_count}', 'info')
        if video_count==rpu_count:
            return True
        if plausibility:
            # Up to 60 frames for rounding; cap that allowance for short clips.
            # Larger but proportionally small discrepancies belong to the exact
            # post-encode check, not to this coarse source sanity check.
            tolerance=min(60,max(1,video_count//20))
            if abs(video_count-rpu_count)<=tolerance or 0.95<=rpu_count/video_count<=1.05:
                self.log('[DV][SOURCE-RPU-CHECK] RPU-Länge plausibel; geringe Abweichung '
                    'wird nach dem Encode exakt geprüft.','info')
                return True
        # A tiny discrepancy or excess RPU is ambiguous; never invent metadata
        # or hide track/count/timeline bugs behind the corrupt-source fallback.
        unusable = rpu_count==0 or (video_count-rpu_count>=2 and rpu_count/video_count<0.95)
        return self.reject(f'Quellvideo/RPU-Frameabweichung: Video={video_count}, RPU={rpu_count}. '
            'Keine automatische RPU-Reparatur.',unusable=unusable)


def _positive_count(*values):
    for value in values:
        try:
            return positive_integer(value)
        except ValueError:
            continue
    return None


def _positive_fraction(*values):
    for value in values:
        if value is None or isinstance(value,bool):
            continue
        try:
            text=str(value).strip()
            parts=text.split(':')
            number=(Fraction(parts[0])*3600+Fraction(parts[1])*60+Fraction(parts[2])
                    if len(parts)==3 else Fraction(text))
            if number>0:
                return number
        except (ValueError,ZeroDivisionError):
            continue
    return None
