# -*- coding: utf-8 -*-
"""Lossless emergency preservation for MP4 timed-text subtitles."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from ..core.lang_codes import lang_iso_tag
from .tool_runner import run_tool


MOV_TEXT_CODECS = {"mov_text", "tx3g"}


def export_mov_text_backup(
    *,
    ffmpeg_path: str,
    input_path: str,
    output_base,
    streams,
    abort_check=None,
    worker=None,
    log=lambda *_args, **_kwargs: None,
):
    """Copy original timed-text tracks into subtitle-only MP4 backup files."""
    # Local import deliberately avoids a module-import cycle: the public result
    # types remain owned by subtitle_sidecar_service.
    from .subtitle_sidecar_service import (
        SubtitleExportFailure,
        SubtitleExportResult,
        safe_lang_tag,
    )

    selected = []
    seen: set[int] = set()
    for stream in streams or ():
        codec = str(getattr(stream, "codec", "") or "").strip().lower()
        try:
            index = int(stream.index)
        except Exception:
            continue
        if codec not in MOV_TEXT_CODECS or index in seen:
            continue
        seen.add(index)
        selected.append(stream)
    if not selected:
        return SubtitleExportResult()

    base = Path(str(output_base))
    keys = [
        (
            safe_lang_tag(lang_iso_tag(getattr(stream, "language", None))),
            bool(getattr(stream, "forced", False)),
        )
        for stream in selected
    ]
    counts = Counter(keys)
    cursors: dict[tuple[str, bool], int] = {}
    exported: list[str] = []
    failures: list[object] = []
    planned = tuple(int(stream.index) for stream in selected)

    for stream, key in zip(selected, keys):
        if abort_check and abort_check():
            return SubtitleExportResult(planned, tuple(exported), tuple(failures), aborted=True)
        lang, forced = key
        number = None
        if counts[key] > 1:
            number = cursors.get(key, 1)
            cursors[key] = number + 1
        forced_part = ".forced" if forced else ""
        num_part = f".{number}" if number is not None else ""
        out_file = Path(f"{base}.{lang}{forced_part}{num_part}.mov_text.mp4")
        if out_file.exists() or out_file.is_symlink():
            reason = "Backup-Zieldatei existiert bereits; stilles Ueberschreiben blockiert"
            failures.append(
                SubtitleExportFailure(int(stream.index), lang, str(stream.codec), reason, str(out_file))
            )
            log(f"  ⚠️  Sub #{stream.index}: {reason}: {out_file.name}", "warn")
            continue

        cmd = [
            ffmpeg_path,
            "-n",
            "-nostdin",
            "-loglevel",
            "error",
            "-i",
            input_path,
            "-map",
            f"0:{stream.index}",
            "-c:s",
            "copy",
            "-map_metadata",
            "-1",
        ]
        if getattr(stream, "language", None):
            cmd += ["-metadata:s:s:0", f"language={str(stream.language).lower()}"]
        title = str(getattr(stream, "title", "") or "").replace("\n", " ").strip()
        if title:
            cmd += ["-metadata:s:s:0", f"title={title}"]
        cmd += ["-disposition:s:0", "forced" if forced else "0", str(out_file)]
        completed = run_tool(
            cmd,
            label=f"mov_text Backup-Sidecar #{stream.index}",
            timeout_s=300,
            worker=worker,
            log=log,
        )
        if getattr(completed, "aborted", False):
            return SubtitleExportResult(planned, tuple(exported), tuple(failures), aborted=True)

        try:
            valid = out_file.exists() and out_file.stat().st_size > 0
        except OSError:
            valid = False
        if completed.returncode == 0 and valid:
            exported.append(str(out_file))
            log(
                f"  📄 mov_text-Fallback gesichert: {out_file.name} (Originalspur, Stream-Copy)",
                "warn",
            )
            continue

        detail = str(completed.stderr or completed.stdout or "").strip()
        reason = f"mov_text-Backup fehlgeschlagen (rc={completed.returncode})"
        if detail:
            reason += f": {detail[-500:]}"
        failures.append(
            SubtitleExportFailure(int(stream.index), lang, str(stream.codec), reason, str(out_file))
        )
        log(f"  ❌ Sub #{stream.index}: {reason}", "error")

    return SubtitleExportResult(
        planned_stream_indices=planned,
        exported_paths=tuple(exported),
        failures=tuple(failures),
    )
