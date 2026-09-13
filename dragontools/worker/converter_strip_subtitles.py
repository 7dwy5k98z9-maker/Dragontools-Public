from __future__ import annotations

from ..rules.subtitle_rules import build_mp4_subtitle_storage_plan, compute_subtitle_plan
from .converter_strip_runtime import subtitle_rules


def build_strip_subtitle_args(worker, mi, ov, container: str) -> list[str]:
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
    if str(container or "mkv").lower() == "mp4":
        return _mp4_subtitle_args(plan, rules)
    return _mkv_subtitle_args(plan)


def _mp4_subtitle_args(plan, rules: dict) -> list[str]:
    storage = build_mp4_subtitle_storage_plan(plan, subtitle_rules=rules, preserve_burn_candidate=True)
    if not storage.internal_streams:
        return ["-sn"]
    args: list[str] = []
    for out_idx, stream in enumerate(storage.internal_streams):
        args += ["-map", f"0:{stream.index}", f"-c:s:{out_idx}", "mov_text"]
        if getattr(stream, "language", None):
            args += [f"-metadata:s:s:{out_idx}", f"language={str(stream.language).lower()}"]
        title = str(getattr(stream, "title", "") or "").replace("\n", " ").strip()
        if title:
            args += [f"-metadata:s:s:{out_idx}", f"title={title}"]
        args += [f"-disposition:s:{out_idx}", "forced" if bool(getattr(stream, "forced", False)) else "0"]
    return args


def _mkv_subtitle_args(plan) -> list[str]:
    streams = ([plan.burn_sub] if plan.burn_sub else []) + list(plan.keep_streams)
    deduped = []
    seen: set[int] = set()
    for stream in streams:
        if stream.index not in seen:
            seen.add(stream.index)
            deduped.append(stream)
    if not deduped:
        return ["-sn"]
    args: list[str] = []
    for stream in deduped:
        args += ["-map", f"0:{stream.index}"]
    return args + ["-c:s", "copy"]
