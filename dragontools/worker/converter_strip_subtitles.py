from __future__ import annotations

from ..rules.subtitle_rules import build_mp4_subtitle_storage_plan, compute_subtitle_plan
from ..core.lang_codes import mkv_language_tags
from .converter_subtitle_args import _subtitle_disposition
from .converter_strip_runtime import subtitle_rules


def build_strip_subtitle_args(worker, mi, ov, container: str, *, exclude_mkv_stream_indices: set[int] | None = None) -> list[str]:
    rules = subtitle_rules(worker)
    plan = compute_subtitle_plan(
        mi.subtitle_streams,
        audio_streams=mi.audio_streams,
        file_override=ov,
        subtitle_rules=rules,
        container_copy_supported=True,
        media_duration_s=getattr(mi, "duration_s", None),
    )
    for warning in getattr(plan, "burn_warnings", ()) or ():
        worker.log(f"⚠️ {warning}", "warn")
    if str(container or "mkv").lower() in {"mp4", "m4v", "mov"}:
        return _mp4_subtitle_args(plan, rules)
    return _mkv_subtitle_args(plan, rules=rules, exclude_stream_indices=exclude_mkv_stream_indices)


def _mp4_subtitle_args(plan, rules: dict) -> list[str]:
    storage = build_mp4_subtitle_storage_plan(plan, subtitle_rules=rules, preserve_burn_candidate=True)
    if not storage.internal_streams:
        return ["-sn"]
    args: list[str] = []
    for out_idx, stream in enumerate(storage.internal_streams):
        args += ["-map", f"0:{stream.index}", f"-c:s:{out_idx}", "mov_text"]
        if getattr(stream, "language", None):
            args += [f"-metadata:s:s:{out_idx}", f"language={mkv_language_tags(stream.language)[0]}"]
        title = str(getattr(stream, "title", "") or "").replace("\n", " ").strip()
        if title:
            args += [f"-metadata:s:s:{out_idx}", f"title={title}"]
        args += [f"-disposition:s:{out_idx}", _subtitle_disposition(stream)]
    return args


def _mkv_subtitle_args(plan, *, rules: dict | None = None, exclude_stream_indices: set[int] | None = None) -> list[str]:
    streams = ([plan.burn_sub] if plan.burn_sub else []) + list(plan.keep_streams)
    from ..rules.subtitle_storage import mkv_internal_subtitle_streams
    deduped = mkv_internal_subtitle_streams(streams, subtitle_rules=rules,
        excluded_indices=exclude_stream_indices or ())

    if not deduped:
        return ["-sn"]
    args: list[str] = []
    for out_idx, stream in enumerate(deduped):
        codec = str(getattr(stream, "codec", "") or "").strip().lower()
        args += ["-map", f"0:{stream.index}"]
        if codec in {"mov_text", "tx3g"}:
            args += [f"-c:s:{out_idx}", "srt"]
        else:
            args += [f"-c:s:{out_idx}", "copy"]
        if getattr(stream, "language", None):
            args += [f"-metadata:s:s:{out_idx}", f"language={mkv_language_tags(stream.language)[0]}"]
        title = str(getattr(stream, "title", "") or "").replace("\n", " ").strip()
        if title:
            args += [f"-metadata:s:s:{out_idx}", f"title={title}"]
        args += [f"-disposition:s:{out_idx}", _subtitle_disposition(stream)]
    return args


def selected_strip_mkv_mov_text_streams(worker, mi, ov, container: str):
    if str(container or "mkv").lower() in {"mp4", "m4v", "mov"}:
        return []
    rules = subtitle_rules(worker)
    plan = compute_subtitle_plan(
        mi.subtitle_streams,
        audio_streams=mi.audio_streams,
        file_override=ov,
        subtitle_rules=rules,
        container_copy_supported=True,
        media_duration_s=getattr(mi, "duration_s", None),
    )
    streams = ([plan.burn_sub] if plan.burn_sub else []) + list(plan.keep_streams)
    result = []
    seen: set[int] = set()
    for stream in streams:
        index = int(stream.index)
        codec = str(getattr(stream, "codec", "") or "").strip().lower()
        if index not in seen and codec in {"mov_text", "tx3g"}:
            seen.add(index)
            result.append(stream)
    return result
