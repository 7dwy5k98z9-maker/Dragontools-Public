from __future__ import annotations

from ..core.models import normalize_override_dict


def build_subtitle_args(worker, input_path, mi, ov, *, container: str, subtitle_rules: dict):
    ov = normalize_override_dict(ov)
    from ..rules import subtitle_rules as subtitle_module
    plan = subtitle_module.compute_subtitle_plan(
        mi.subtitle_streams, audio_streams=mi.audio_streams, file_override=ov,
        subtitle_rules=subtitle_rules, container_copy_supported=True,
        media_duration_s=getattr(mi, "duration_s", None),
    )
    burn_sub = plan.burn_sub
    keep = list(plan.keep_streams)
    for warning in getattr(plan, "burn_warnings", ()) or ():
        worker.log(f"⚠️ {warning}", "warn")
    if str(container or "mkv").lower() == "mp4":
        return _mp4_args(worker, plan, burn_sub, subtitle_rules)
    return _mkv_args(worker, burn_sub, keep)


def _mp4_args(worker, plan, burn_sub, rules):
    from ..rules import subtitle_rules as subtitle_module
    storage = subtitle_module.build_mp4_subtitle_storage_plan(plan, subtitle_rules=rules)
    if burn_sub:
        worker._logger.decision(f"Sub #{burn_sub.index} ({burn_sub.language},forced={burn_sub.forced})→burn-in")
    if subtitle_module.mp4_sidecars_enabled(rules):
        if storage.external_streams:
            worker._logger.decision("MP4-Sidecars aktiv: ausgewählte nicht eingebrannte Untertitel werden extern gespeichert")
        return (burn_sub if burn_sub else []), ["-sn"]
    args: list[str] = []
    for out_idx, stream in enumerate(storage.internal_streams):
        args += ["-map", f"0:{stream.index}", f"-c:s:{out_idx}", "mov_text"]
        if getattr(stream, "language", None):
            args += [f"-metadata:s:s:{out_idx}", f"language={str(stream.language).lower()}"]
        title = str(getattr(stream, "title", "") or "").replace("\n", " ").strip()
        if title:
            args += [f"-metadata:s:s:{out_idx}", f"title={title}"]
        args += [f"-disposition:s:{out_idx}", "forced" if bool(getattr(stream, "forced", False)) else "0"]
        worker._logger.decision(f"Sub #{stream.index} ({stream.language}, {stream.codec}, forced={stream.forced})→mov_text intern")
    for stream in storage.external_streams:
        worker._logger.decision(f"Sub #{stream.index} ({stream.language}, {stream.codec})→Sidecar (MP4-Kompatibilität)")
    return (burn_sub if burn_sub else []), (args or ["-sn"])


def _mkv_args(worker, burn_sub, keep):
    if burn_sub:
        worker._logger.decision(f"Sub #{burn_sub.index} ({burn_sub.language},forced={burn_sub.forced})→burn-in")
        if not keep:
            return burn_sub, ["-sn"]
    elif not keep:
        worker._logger.decision("Keine kompatiblen Untertitel - keine Subs übernommen")
        return [], ["-sn"]
    args: list[str] = []
    for stream in keep:
        args += ["-map", f"0:{stream.index}"]
        worker._logger.decision(f"Sub #{stream.index} ({stream.language},forced={stream.forced})→stream copy")
    return (burn_sub if burn_sub else []), args + ["-c:s", "copy"]
