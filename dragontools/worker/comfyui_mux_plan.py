"""Build the ComfyUI mux command without executing or committing files."""
from __future__ import annotations

from .log_dispatch import dispatch_log


def comfyui_output_args(container, output_args):
    args = list(output_args)
    if str(container).lower() in {"mp4", "m4v", "mov"}:
        # Preserve AAC preroll in edit lists after restoring the HDR origin.
        position = args.index("-avoid_negative_ts")
        args[position + 1] = "disabled"
    return args


def build_comfyui_mux_command(ffmpeg, request, hdr_video, rendered, output_args, subtitle_args):
    plan = request.plan
    source_origin = getattr(rendered, "source_input_offset_s", None)
    copy_timestamps = []
    source_timestamp_args = []
    if source_origin is not None:
        copy_timestamps = ["-copyts"]
        source_timestamp_args = ["-itsoffset", f"{source_origin:.9f}"]
    offset = float(getattr(rendered, "video_offset_s", 0.0))
    video_input_args = ["-itsoffset", f"{offset:.9f}"] if offset else []
    return (
        [ffmpeg, "-y", "-loglevel", "error"]
        + copy_timestamps
        + list(getattr(plan, "audio_input_args", []) or [])
        + source_timestamp_args
        + ["-i", request.input_path]
        + video_input_args
        + ["-i", str(hdr_video), "-map", "1:v:0", "-c:v", "copy"]
        + list(plan.audio_args)
        + list(subtitle_args)
        + list(output_args)
        + [request.output_path]
    )


def log_comfyui_completion(log, rendered):
    if log:
        vram = f", Peak-VRAM {rendered.peak_vram_bytes / 1024**3:.2f} GiB" if rendered.peak_vram_bytes else ""
        elapsed = f", {rendered.elapsed_s:.1f}s" if rendered.elapsed_s > 0 else ""
        dispatch_log(log, f"✅ ComfyUI/HDRTVDM: {rendered.frames} Frames verarbeitet{elapsed}{vram}.", "info")
