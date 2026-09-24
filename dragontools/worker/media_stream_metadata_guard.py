"""Revalidate queued tracks and commit MKV/NFO metadata from isolated copies."""
from __future__ import annotations

import json
from contextlib import nullcontext
import os
from pathlib import Path
import shutil
import tempfile
import threading

from ..core.lang_codes import canonical_lang
from ..core.mkv_track_metadata import apply_mkv_track_metadata
from ..core.nfo_stream_metadata import resolve_existing_nfo, stage_stream_language_update
from .tool_runner import run_tool

_EDIT_LOCK = threading.RLock()


def file_signature(path):
    stat = Path(path).stat()
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def _validate_track(issue, tools, worker):
    result = run_tool(
        [str(getattr(tools, "ffprobe", "ffprobe")), "-v", "error",
         "-show_streams", "-of", "json", issue.path],
        worker=worker, abort_on_request=True, timeout_s=60,
    )
    if result.returncode or result.aborted:
        raise ValueError("Aktuelle Trackdaten konnten nicht sicher geprüft werden.")
    streams = json.loads(result.stdout).get("streams", [])
    typed = [s for s in streams if s.get("codec_type") == issue.stream_type]
    ordinal = int(issue.stream_ordinal or 0)
    if not 0 < ordinal <= len(typed):
        raise ValueError("Trackreihenfolge hat sich geändert; Mediathek neu analysieren.")
    stream = typed[ordinal - 1]
    tags = {str(k).lower(): v for k, v in stream.get("tags", {}).items()}

    def language(value):
        return canonical_lang(str(value or "und")) or "und"

    if (stream.get("index") != issue.stream_index
            or stream.get("codec_name", "").casefold() != issue.codec.casefold()
            or language(tags.get("language")) != language(issue.language)
            or str(tags.get("title") or "") != issue.track_title
            or bool(stream.get("disposition", {}).get("forced", 0)) != issue.forced
            or (issue.channels is not None and stream.get("channels") != issue.channels)):
        raise ValueError("Trackdaten sind veraltet; Mediathek neu analysieren und Fix neu auswählen.")


def _stage_nfo_language(issue, *, temp_dir: Path, language: str | None):
    """Prepare an existing NFO update without modifying the live file."""
    if not str(language or "").strip():
        return None
    nfo_path = resolve_existing_nfo(issue.path, getattr(issue, "nfo_path", ""))
    if nfo_path is None:
        return None
    if nfo_path.is_symlink() or nfo_path.is_junction():
        raise ValueError("NFO-Korrektur über Verknüpfungen ist nicht erlaubt.")

    before = file_signature(nfo_path)
    staged = temp_dir / "staged.nfo"
    backup = temp_dir / "original.nfo"
    shutil.copy2(nfo_path, backup)
    changed, message = stage_stream_language_update(
        nfo_path,
        staged,
        stream_type=issue.stream_type,
        ordinal=int(issue.stream_ordinal or 0),
        language=str(language),
    )
    return {
        "path": nfo_path,
        "before": before,
        "staged": staged if changed else None,
        "backup": backup,
        "message": message,
    }


def edit_queued_track(issue, *, tools, worker=None, language=None, title=None):
    def aborted():
        return bool(worker is not None and getattr(worker, "abort_requested", False))

    with _EDIT_LOCK:
        path = Path(issue.path)
        try:
            if aborted():
                return False, "Track-Korrektur wurde abgebrochen."
            if path.is_symlink() or path.is_junction():
                return False, "Track-Korrektur über Verknüpfungen ist nicht erlaubt."
            before = file_signature(path)
            if not issue.source_signature or tuple(issue.source_signature) != before:
                return False, "Mediendatei wurde geändert; Fix neu auswählen."
            _validate_track(issue, tools, worker)
            if aborted() or file_signature(path) != before:
                return False, "Abbruch oder geänderte Quelldatei; keine Metadaten geschrieben."

            with tempfile.TemporaryDirectory(prefix=".dragon_track_", dir=path.parent) as tmp:
                temp_dir = Path(tmp)
                staged = temp_dir / path.name
                shutil.copy2(path, staged)
                if aborted() or file_signature(path) != before:
                    return False, "Abbruch oder geänderte Quelldatei; Original bleibt erhalten."

                ok, message = apply_mkv_track_metadata(
                    str(staged), stream_type=issue.stream_type,
                    ordinal=int(issue.stream_ordinal or 0),
                    mkvpropedit_path=str(getattr(tools, "mkvpropedit", "")),
                    language=language, title=title,
                )
                if not ok:
                    return False, message

                # If an NFO stores streamdetails, stage the matching language
                # update before either live file is replaced.  A malformed or
                # ambiguous NFO therefore blocks the whole language fix.
                nfo_state = _stage_nfo_language(issue, temp_dir=temp_dir, language=language)

                with getattr(worker, "metadata_commit_lock", nullcontext()):
                    if aborted() or file_signature(path) != before:
                        return False, "Abbruch oder geänderte Quelldatei; Original bleibt erhalten."
                    if nfo_state is not None and file_signature(nfo_state["path"]) != nfo_state["before"]:
                        return False, "NFO wurde zwischenzeitlich geändert; keine Metadaten geschrieben."

                    nfo_committed = False
                    try:
                        if nfo_state is not None and nfo_state["staged"] is not None:
                            os.replace(nfo_state["staged"], nfo_state["path"])
                            nfo_committed = True
                        os.replace(staged, path)
                    except OSError:
                        if nfo_committed and nfo_state is not None and Path(nfo_state["backup"]).exists():
                            os.replace(nfo_state["backup"], nfo_state["path"])
                        raise

                if nfo_state is not None:
                    nfo_message = str(nfo_state.get("message") or "").strip()
                    if nfo_message:
                        message = f"{message} {nfo_message}".strip()
                return True, message
        except (OSError, ValueError, TypeError) as exc:
            return False, f"Track-Korrektur sicher abgelehnt: {exc}"
