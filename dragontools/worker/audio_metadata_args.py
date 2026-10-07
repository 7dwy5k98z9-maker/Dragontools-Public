"""Shared audio title, language and disposition boundary for FFmpeg muxes."""
from ..core.audio_titles import build_audio_title
from ..core.lang_codes import mkv_language_tags
from ..rules.audio_plan import output_default_for_decision


def audio_output_title(decision):
    stream = decision.stream
    transcode = bool(getattr(decision, "needs_transcode", False))
    return build_audio_title(
        language=getattr(stream, "language", None),
        codec=getattr(decision, "target_codec", "") if transcode else getattr(stream, "codec", ""),
        channels=getattr(decision, "target_channels", None) if transcode else getattr(stream, "channels", None),
        bitrate_bps=getattr(decision, "target_bitrate", None) if transcode else getattr(stream, "bitrate", None),
    )


def audio_output_forced(decision):
    return bool(getattr(decision.stream, "forced", False)) and not bool(getattr(decision, "is_extra_stereo", False))


def audio_metadata_args(decision):
    index = decision.out_idx
    args = []
    language = getattr(decision.stream, "language", None)
    if language:
        args += [f"-metadata:s:a:{index}", f"language={mkv_language_tags(language)[0]}"]
    title = audio_output_title(decision)
    args += [f"-metadata:s:a:{index}", f"title={title}"]
    # MP4 stores its display label in the handler name rather than the title tag.
    args += [f"-metadata:s:a:{index}", f"handler_name={title}"]
    flags = []
    if output_default_for_decision(decision):
        flags.append("default")
    if audio_output_forced(decision):
        flags.append("forced")
    return args + [f"-disposition:a:{index}", "+".join(flags) or "0"]
