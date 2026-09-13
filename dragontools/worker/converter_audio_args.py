from __future__ import annotations

from ..core.audio_titles import build_audio_title
from ..rules.audio_plan import audio_filter_chain, audio_input_args_for_plan, compute_audio_track_plan


def build_audio_args(worker, mi, ov, container) -> list[str]:
    plan = compute_audio_track_plan(audio_streams=mi.audio_streams, file_override=ov, container=container)
    if not plan:
        return ["-an"]
    args: list[str] = []
    for decision in plan:
        chosen, out_idx = decision.stream, decision.out_idx
        for note in getattr(decision, "processing_notes", ()) or ():
            worker._logger.decision(f"Audio Spur {chosen.index}: {note}")
        args += ["-map", f"0:{chosen.index}"]
        if decision.is_extra_stereo:
            bitrate_k = max(64, int(decision.target_bitrate / 1000) if decision.target_bitrate else 256)
            args += [f"-c:a:{out_idx}", decision.target_codec, f"-ac:a:{out_idx}", "2", f"-b:a:{out_idx}", f"{bitrate_k}k"]
            filters = audio_filter_chain(decision)
            if filters:
                args += [f"-filter:a:{out_idx}", filters]
            worker._logger.audio(chosen.index, chosen.codec, "transcode", decision.target_codec, 2, bitrate_k, getattr(chosen, "language", None))
            lang = getattr(chosen, "language", None) or ""
            worker._logger.decision(f"  ↳ Zusatz-Stereo-Downmix ({decision.target_codec.upper()}) aus Spur #{chosen.index}" + (f" ({lang})" if lang else ""))
        elif decision.needs_transcode:
            bitrate_k = max(1, int(decision.target_bitrate / 1000) if decision.target_bitrate else 256)
            args += [f"-c:a:{out_idx}", decision.target_codec, f"-ac:a:{out_idx}", str(decision.target_channels), f"-b:a:{out_idx}", f"{bitrate_k}k"]
            filters = audio_filter_chain(decision)
            if filters:
                args += [f"-filter:a:{out_idx}", filters]
            worker._logger.audio(chosen.index, chosen.codec, "transcode", decision.target_codec, decision.target_channels, bitrate_k, getattr(chosen, "language", None))
        else:
            args += [f"-c:a:{out_idx}", "copy"]
            worker._logger.audio(chosen.index, chosen.codec, "copy", language=getattr(chosen, "language", None))
        _append_audio_metadata(args, decision, chosen, out_idx)
    return args


def build_audio_input_args(mi, ov, container) -> list[str]:
    plan = compute_audio_track_plan(audio_streams=mi.audio_streams, file_override=ov, container=container)
    return audio_input_args_for_plan(plan)


def _append_audio_metadata(args: list[str], decision, chosen, out_idx: int) -> None:
    title_codec = decision.target_codec if decision.needs_transcode else chosen.codec
    title_channels = decision.target_channels if decision.needs_transcode else getattr(chosen, "channels", None)
    title_bitrate = decision.target_bitrate if decision.needs_transcode else getattr(chosen, "bitrate", None)
    title = build_audio_title(language=getattr(chosen, "language", None), codec=title_codec, channels=title_channels, bitrate_bps=title_bitrate)
    if getattr(chosen, "language", None):
        args += [f"-metadata:s:a:{out_idx}", f"language={chosen.language.lower()}"]
    args += [f"-metadata:s:a:{out_idx}", f"title={title}"]
