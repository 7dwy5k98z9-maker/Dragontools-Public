"""Plan lossless timed-text backup files without touching the filesystem."""

from collections import Counter
from pathlib import Path
from ..core.lang_codes import lang_iso_tag, mkv_language_tags
from .converter_subtitle_args import _subtitle_disposition
from .subtitle_export_models import safe_lang_tag
from .subtitle_sidecar_targets import SidecarTarget

MOV_TEXT_CODECS = {"mov_text", "tx3g"}


def build_mov_text_backup_targets(output_base, streams):
    selected = []
    seen = set()
    for stream in streams or ():
        if str(stream.codec or "").lower() not in MOV_TEXT_CODECS:
            continue
        if type(stream.index) is not int or stream.index < 0:
            raise ValueError("Ungültiger mov_text-Streamindex.")
        if stream.index not in seen:
            seen.add(stream.index)
            selected.append(stream)
    keys = [
        (safe_lang_tag(lang_iso_tag(stream.language)), bool(stream.forced))
        for stream in selected
    ]
    counts, cursors = Counter(keys), {}
    targets = []
    for stream, key in zip(selected, keys):
        lang, forced = key
        number = None
        if counts[key] > 1:
            number = cursors.get(key, 1)
            cursors[key] = number + 1
        flags = (".default" if bool(getattr(stream, "default", False)) else "") + (
            ".forced" if forced else ""
        )
        path = (
            f"{Path(str(output_base))}.{lang}{flags}"
            + (f".{number}" if number else "")
            + ".mov_text.mp4"
        )
        args = ["-c:s", "copy", "-map_metadata", "-1"]
        if stream.language:
            args += [
                "-metadata:s:s:0",
                f"language={mkv_language_tags(stream.language)[0]}",
            ]
        title = str(getattr(stream, "title", "") or "").replace("\n", " ").strip()
        if title:
            args += [
                "-metadata:s:s:0",
                f"title={title}",
                "-metadata:s:s:0",
                f"handler_name={title}",
            ]
        args += ["-disposition:s:0", _subtitle_disposition(stream)]
        targets.append(
            SidecarTarget(stream, lang, key, number, path, tuple(args), "mov_text")
        )
    return targets
