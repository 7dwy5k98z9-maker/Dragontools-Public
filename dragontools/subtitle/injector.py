"""Subtitle injection: plan against inventories, mux, verify, publish."""

from __future__ import annotations
from ..worker.log_dispatch import dispatch_log
import json
import uuid
from pathlib import Path
from ..core.lang_codes import mkv_language_tags
from ..core.output_timestamps import build_output_timestamp_args
from ..core.timeout_settings import get_timeout
from ..core.tool_paths import get_tool_paths
from ..worker.tool_runner import run_tool
from .tool_logging import log_tool_error as _log_tool_error
from .output_safety import (
    publish_subtitle_stage,
    reject_source_output,
    stopped,
    valid_stream_indices,
)
from .media_verification import build_injection_plan, verify_injection
from .matroska_tracks import parse_matroska_tracks, injection_track_options


def _staging_output(output):
    return output.with_name(
        f".{output.stem}.dragontools-{uuid.uuid4().hex}{output.suffix}"
    )


def _commit_staging(stage, output, *, overwrite):
    try:
        publish_subtitle_stage(stage, output, overwrite=overwrite)
    except FileExistsError:
        return False
    return True


def _ffprobe_for_ffmpeg(ffmpeg, ffprobe):
    if ffprobe:
        return str(ffprobe)
    path = Path(ffmpeg)
    return str(
        path.with_name("ffprobe.exe" if path.suffix.lower() == ".exe" else "ffprobe")
    )


def _probe_subtitle_count(video_path, *, ffprobe, logger=None, worker=None):
    try:
        result = run_tool(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "s",
                "-show_entries",
                "stream=index",
                "-of",
                "json",
                video_path,
            ],
            label="Subtitle-Injection ffprobe",
            timeout_s=30,
            worker=worker,
        )
        if result.returncode != 0 or stopped(result, worker):
            return None
        return len(valid_stream_indices(json.loads(result.stdout).get("streams")))
    except Exception as exc:
        _log_tool_error(logger, Path(ffprobe).name, None, exc=exc)
        return None


def _allowed_output(output, *sources, overwrite, logger):
    if reject_source_output(output, *sources):
        if logger:
            dispatch_log(
                logger, "❌ Untertitel-Ausgabe darf keine Quelldatei ersetzen."
            )
        return False
    if (output.exists() or output.is_symlink()) and not overwrite:
        if logger:
            dispatch_log(logger, f"❌ Zieldatei existiert bereits: {output}")
        return False
    return True


def _mux_and_publish(
    command,
    output,
    stage,
    plan,
    *,
    ffprobe,
    worker,
    logger,
    overwrite,
    warning_ok=False,
):
    verified = False
    try:
        result = run_tool(
            command,
            label="Subtitle-Injection",
            timeout_s=get_timeout("subtitle_inject"),
            worker=worker,
            log=(lambda msg, _level="info": dispatch_log(logger, msg))
            if logger
            else None,
        )
        accepted = {0, 1} if warning_ok else {0}
        if result.returncode not in accepted or stopped(result, worker):
            raise ValueError("Untertitel-Mux fehlgeschlagen oder abgebrochen.")
        verify_injection(stage, plan, ffprobe=ffprobe, worker=worker, logger=logger)
        if stopped(result, worker):
            raise ValueError("Untertitel-Injection vor dem Speichern abgebrochen.")
        verified = True
        if not _commit_staging(stage, output, overwrite=overwrite):
            raise FileExistsError(f"Ziel wurde zwischenzeitlich belegt: {output}")
        if result.returncode == 1 and logger:
            dispatch_log(
                logger,
                "⚠️ MKVToolNix meldete Warnungen; die Medienausgabe wurde geprüft.",
            )
        return True
    except Exception as exc:
        if verified:
            if logger:
                dispatch_log(
                    logger,
                    f"❌ Speichern fehlgeschlagen: {exc}. Geprüfte Ausgabe bleibt zur Wiederherstellung: {stage}",
                )
        else:
            stage.unlink(missing_ok=True)
            _log_tool_error(logger, Path(command[0]).name, None, exc=exc)
        return False


def _identify(mkvmerge, path, worker):
    result = run_tool(
        [mkvmerge, "-J", str(path)],
        label="Subtitle-Injection MKV-Inventar",
        timeout_s=60,
        worker=worker,
    )
    if result.returncode != 0 or stopped(result, worker):
        raise ValueError("MKVToolNix-Inventar fehlgeschlagen.")
    return parse_matroska_tracks(result.stdout)


def inject_with_mkvmerge(
    video_path,
    sub_path,
    output_path,
    language="de",
    forced=False,
    logger=None,
    mkvmerge="mkvmerge",
    worker=None,
    overwrite=False,
    title="Deutsch",
    ffprobe=None,
):
    output = Path(output_path)
    if not _allowed_output(
        output, video_path, sub_path, overwrite=overwrite, logger=logger
    ):
        return False
    stage = _staging_output(output)
    probe = str(
        ffprobe
        or getattr(getattr(worker, "tools", None), "ffprobe", "")
        or get_tool_paths().ffprobe
    )
    try:
        plan = build_injection_plan(
            video_path,
            sub_path,
            output_path=output,
            ffprobe=probe,
            language=language,
            forced=forced,
            title=title,
            worker=worker,
            logger=logger,
        )
        flags = injection_track_options(
            _identify(mkvmerge, video_path, worker), plan.source_streams
        )
        extra = _identify(mkvmerge, sub_path, worker)
        if len(extra) != 1 or extra[0].get("type") != "subtitles":
            raise ValueError(
                "Zusatzdatei enthält nicht genau eine Matroska-Untertitelspur."
            )
        track_id = extra[0]["id"]
        cmd = [
            mkvmerge,
            "-o",
            str(stage),
            *flags,
            video_path,
            "--no-video",
            "--no-audio",
            "--no-buttons",
            "--no-attachments",
            "--no-chapters",
            "--no-global-tags",
            "--no-track-tags",
            "--subtitle-tracks",
            str(track_id),
            "--language",
            f"{track_id}:{mkv_language_tags(language)[0]}",
            "--track-name",
            f"{track_id}:{title}",
            "--default-track-flag",
            f"{track_id}:no",
            "--forced-display-flag",
            f"{track_id}:{'yes' if forced else 'no'}",
            sub_path,
        ]
    except Exception as exc:
        _log_tool_error(logger, Path(mkvmerge).name, None, exc=exc)
        return False
    return _mux_and_publish(
        cmd,
        output,
        stage,
        plan,
        ffprobe=probe,
        worker=worker,
        logger=logger,
        overwrite=overwrite,
        warning_ok=True,
    )


def _source_dispositions(plan):
    args = []
    for kind, letter in [("audio", "a"), ("subtitle", "s")]:
        rows = [row for row in plan.source_streams if row["codec_type"] == kind]
        if kind == "subtitle":
            rows = rows[: plan.new_subtitle_index]
        for index, row in enumerate(rows):
            flags = row.get("disposition") or {}
            disposition = (
                "+".join(key for key in ("default", "forced") if flags.get(key)) or "0"
            )
            args += [f"-disposition:{letter}:{index}", disposition]
            title = (row.get("tags") or {}).get("title")
            if title:
                args += [
                    f"-metadata:s:{letter}:{index}", f"title={title}",
                    f"-metadata:s:{letter}:{index}", f"handler_name={title}",
                ]
    return args


def inject_with_ffmpeg(
    video_path,
    sub_path,
    output_path,
    language="de",
    ffmpeg="ffmpeg",
    logger=None,
    subtitle_codec=None,
    map_existing_subtitles=True,
    worker=None,
    overwrite=False,
    forced=False,
    ffprobe=None,
    existing_subtitle_count=None,
    title="Deutsch",
):
    output = Path(output_path)
    if not _allowed_output(
        output, video_path, sub_path, overwrite=overwrite, logger=logger
    ):
        return False
    probe = _ffprobe_for_ffmpeg(ffmpeg, ffprobe)
    if map_existing_subtitles and existing_subtitle_count is None:
        existing_subtitle_count = _probe_subtitle_count(
            video_path, ffprobe=probe, logger=logger, worker=worker
        )
        if existing_subtitle_count is None:
            if logger:
                dispatch_log(
                    logger, "❌ Neuer Untertitel-Index ist nicht sicher bestimmbar."
                )
            return False
    try:
        plan = build_injection_plan(
            video_path,
            sub_path,
            output_path=output,
            ffprobe=probe,
            language=language,
            forced=forced,
            title=title,
            subtitle_codec=subtitle_codec,
            map_existing_subtitles=map_existing_subtitles,
            existing_subtitle_count=existing_subtitle_count,
            worker=worker,
            logger=logger,
        )
    except Exception as exc:
        _log_tool_error(logger, Path(probe).name, None, exc=exc)
        return False
    index = plan.new_subtitle_index
    stage = _staging_output(output)
    cmd = [ffmpeg, "-n", "-nostdin", "-i", video_path, "-i", sub_path]
    if map_existing_subtitles:
        cmd += ["-map", "0", "-map", "1:s:0", "-c", "copy"]
    else:
        cmd += [
            "-map",
            "0",
            "-map",
            "-0:s?",
            "-map",
            "1:s:0",
            "-map_metadata",
            "0",
            "-map_chapters",
            "0",
            "-c",
            "copy",
        ]
    if subtitle_codec:
        cmd += [f"-c:s:{index}", subtitle_codec]
    cmd += [
        *_source_dispositions(plan),
        f"-metadata:s:s:{index}",
        f"language={mkv_language_tags(language)[0]}",
        f"-metadata:s:s:{index}",
        f"title={title}",
        f"-metadata:s:s:{index}",
        f"handler_name={title}",
        f"-disposition:s:{index}",
        "forced" if forced else "0",
        *build_output_timestamp_args(output_path),
        str(stage),
    ]
    return _mux_and_publish(
        cmd,
        output,
        stage,
        plan,
        ffprobe=probe,
        worker=worker,
        logger=logger,
        overwrite=overwrite,
    )
