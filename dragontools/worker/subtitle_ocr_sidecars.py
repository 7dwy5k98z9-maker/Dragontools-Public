"""Optional OCR sidecars; original bitmap preservation remains independent."""

from collections import Counter
from pathlib import Path
from ..core.lang_codes import lang_iso_tag
from ..core.media_library_fix_queue import MediaLibraryFixIssue
from .subtitle_export_models import safe_lang_tag, sidecar_filename
from .subtitle_sidecar_targets import add_default_sidecar_flag


def build_pgs_ocr_jobs(input_path, output_base, media_info, streams):
    ordinals = {
        stream.index: pos + 1 for pos, stream in enumerate(media_info.subtitle_streams)
    }
    selected = list(streams or ())
    keys = [
        (safe_lang_tag(lang_iso_tag(stream.language)), bool(stream.forced))
        for stream in selected
    ]
    counts, cursors = Counter(keys), {}
    jobs = []
    for stream, key in zip(selected, keys):
        lang, forced = key
        number = None
        if counts[key] > 1:
            number = cursors.get(key, 1)
            cursors[key] = number + 1
        target = Path(
            add_default_sidecar_flag(
                sidecar_filename(output_base, lang, forced, ".srt", number),
                is_default=bool(getattr(stream, "default", False)),
                forced=forced,
                number=number,
            )
        )
        issue = MediaLibraryFixIssue(
            media_id=0,
            path=input_path,
            title=Path(input_path).stem,
            item_type="video",
            issue_type="bitmap_subtitle_ocr",
            action="ocr_bitmap_subtitle",
            problem="PGS→SRT Encode-OCR",
            action_label="PGS→SRT",
            stream_index=stream.index,
            stream_type="subtitle",
            stream_ordinal=ordinals.get(stream.index),
            codec=stream.codec,
            language=stream.language,
            track_title=str(getattr(stream, "title", "") or ""),
            forced=forced,
        )
        jobs.append((issue, target))
    return jobs


def export_pgs_ocr_sidecars(
    *,
    input_path,
    output_base,
    media_info,
    streams,
    worker,
    log,
    abort_check,
    service_factory,
):
    if (
        worker is None
        or getattr(worker, "settings", None) is None
        or getattr(worker, "tools", None) is None
    ):
        log(
            "  ⚠️ PGS→SRT übersprungen: Worker-Laufzeit für OCR nicht verfügbar.", "warn"
        )
        return [], False
    service = service_factory(
        settings=worker.settings, tools=worker.tools, log=log, worker=worker
    )
    exported = []
    for issue, target in build_pgs_ocr_jobs(
        input_path, output_base, media_info, streams
    ):
        if abort_check():
            return exported, True
        try:
            result = service.create_srt(issue, target)
        except Exception as exc:
            if abort_check():
                return exported, True
            log(
                f"  ⚠️ PGS→SRT für Sub #{issue.stream_index} übersprungen: {exc}. Original-PGS bleibt gemäß Regelwerk erhalten.",
                "warn",
            )
            continue
        exported.append(str(result))
        log(f"  ✅ PGS→SRT erzeugt: {result.name}", "info")
    return exported, False
