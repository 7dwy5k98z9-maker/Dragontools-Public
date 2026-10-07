"""Lossless emergency preservation for MP4 timed-text subtitles."""

from .subtitle_export_models import SubtitleExportResult
from .subtitle_movtext_plan import MOV_TEXT_CODECS, build_mov_text_backup_targets
from .subtitle_sidecar_exporter import SubtitleSidecarExporter
from .tool_runner import run_tool
from .log_dispatch import dispatch_log


def export_mov_text_backup(
    *,
    ffmpeg_path,
    input_path,
    output_base,
    streams,
    abort_check=None,
    worker=None,
    log=lambda *_a, **_k: None,
):
    callback = log
    log = lambda message, level="info": dispatch_log(callback, message, level)
    targets = build_mov_text_backup_targets(output_base, streams)
    planned = tuple(target.stream.index for target in targets)
    exported, failures = [], []
    exporter = SubtitleSidecarExporter(
        ffmpeg_path=ffmpeg_path, worker=worker, log=log, run=run_tool
    )
    for target in targets:
        if abort_check and abort_check():
            return SubtitleExportResult(
                planned, tuple(exported), tuple(failures), aborted=True
            )
        ok, failure, aborted = exporter.export_target(
            input_path, target, abort_check=abort_check
        )
        if ok:
            exported.append(target.output_path)
            log(
                f"  📄 mov_text-Fallback gesichert: {target.output_path} (Originalspur, Stream-Copy)",
                "warn",
            )
        if failure:
            failures.append(failure)
        if aborted:
            return SubtitleExportResult(
                planned, tuple(exported), tuple(failures), aborted=True
            )
    return SubtitleExportResult(planned, tuple(exported), tuple(failures))
