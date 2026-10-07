from __future__ import annotations

from ..core.lang_codes import mkv_language_tags
from ..rules.audio_plan import (
    audio_filter_chain,
    audio_input_args_for_plan,
    compute_audio_track_plan,
    output_default_for_decision,
)


def build_strip_audio_args(mi, ov, container: str) -> tuple[list[str], list[str]]:
    plan = compute_audio_track_plan(audio_streams=mi.audio_streams, file_override=ov, container=container)
    input_args = audio_input_args_for_plan(plan)
    if not plan:
        return input_args, ["-an"]

    args: list[str] = []
    for decision in plan:
        args += ["-map", f"0:{decision.stream.index}"]
        if not decision.needs_transcode:
            args += [f"-c:a:{decision.out_idx}", "copy"]
            args += [
                f"-disposition:a:{decision.out_idx}",
                "default" if output_default_for_decision(decision) else "0",
            ]
            if getattr(decision.stream, "language", None):
                args += [
                    f"-metadata:s:a:{decision.out_idx}",
                    f"language={mkv_language_tags(decision.stream.language)[0]}",
                ]
            continue
        bitrate_k = max(1, int(decision.target_bitrate / 1000) if decision.target_bitrate else 256)
        args += [
            f"-c:a:{decision.out_idx}", decision.target_codec,
            f"-ac:a:{decision.out_idx}", str(decision.target_channels),
            f"-b:a:{decision.out_idx}", f"{bitrate_k}k",
        ]
        filters = audio_filter_chain(decision)
        if filters:
            args += [f"-filter:a:{decision.out_idx}", filters]
        args += [
            f"-disposition:a:{decision.out_idx}",
            "default" if output_default_for_decision(decision) else "0",
        ]
        if getattr(decision.stream, "language", None):
            args += [
                f"-metadata:s:a:{decision.out_idx}",
                f"language={mkv_language_tags(decision.stream.language)[0]}",
            ]
    return input_args, args
