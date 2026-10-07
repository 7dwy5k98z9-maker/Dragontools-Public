"""Execute, verify and exclusively publish a planned subtitle sidecar."""

import uuid
from pathlib import Path

from ..subtitle.output_safety import (
    publish_subtitle_stage,
    reject_source_output,
    stopped,
)
from ..subtitle.media_verification import verify_subtitle_export
from ..subtitle.matroska_tracks import resolve_subtitle_track_id
from .subtitle_export_models import SubtitleExportFailure


def sibling_ffprobe(ffmpeg):
    path = Path(ffmpeg)
    return str(
        path.with_name("ffprobe.exe" if path.suffix.lower() == ".exe" else "ffprobe")
    )


class SubtitleSidecarExporter:
    def __init__(self, *, ffmpeg_path, worker, log, run):
        self.ffmpeg = ffmpeg_path
        self.worker, self.log, self.run = worker, log, run
        self.ffprobe = str(
            getattr(getattr(worker, "tools", None), "ffprobe", "")
            or sibling_ffprobe(ffmpeg_path)
        )

    def export_target(self, input_path, target, *, abort_check=None):
        stream, output = target.stream, Path(target.output_path)
        codec = target.output_codec
        stage = output.with_name(
            f".{output.stem}.dragontools-{uuid.uuid4().hex}{output.suffix}"
        )
        verified = False
        try:
            if (
                output.exists()
                or output.is_symlink()
                or reject_source_output(output, input_path)
            ):
                raise FileExistsError(
                    "Zieldatei existiert bereits oder bezeichnet die Quelle."
                )
            if type(stream.index) is not int or stream.index < 0:
                raise ValueError("Ungültiger FFmpeg-Untertitelindex.")
            completed = self.run(
                [
                    self.ffmpeg,
                    "-n",
                    "-nostdin",
                    "-loglevel",
                    "error",
                    "-i",
                    input_path,
                    "-map",
                    f"0:{stream.index}",
                    *target.codec_args,
                    str(stage),
                ],
                label=f"Untertitel-Sidecar #{stream.index}",
                timeout_s=300,
                worker=self.worker,
                log=self.log,
            )
            if stopped(completed, self.worker) or (abort_check and abort_check()):
                raise InterruptedError(
                    "Sidecar-Export abgebrochen oder Zeitlimit überschritten."
                )
            if completed.returncode != 0:
                if codec not in {"hdmv_pgs_subtitle", "pgs"} or not self.pgs_fallback(
                    input_path, stream, stage
                ):
                    raise ValueError(
                        f"Export fehlgeschlagen (rc={completed.returncode}): {completed.stderr or completed.stdout}"
                    )
            if not stage.is_file() or stage.stat().st_size <= 0:
                raise ValueError("Export fehlgeschlagen: keine Ausgabedatei.")
            verify_subtitle_export(
                stage,
                expected_codec=codec,
                ffprobe=self.ffprobe,
                worker=self.worker,
                logger=lambda message: self.log(message, "warn"),
            )
            if stopped(completed, self.worker) or (abort_check and abort_check()):
                raise InterruptedError("Sidecar-Export vor dem Speichern abgebrochen.")
            verified = True
            publish_subtitle_stage(stage, output)
            self.log(f"  📄 Sidecar OK: {output.name}", "info")
            return True, None, False
        except Exception as exc:
            if verified:
                reason = f"Commit fehlgeschlagen: {exc}; geprüfte Ausgabe bleibt erhalten: {stage}"
            else:
                stage.unlink(missing_ok=True)
                reason = str(exc)
            self.log(f"  ⚠️ Sub #{stream.index}: {reason}", "warn")
            aborted = isinstance(exc, InterruptedError) and not getattr(
                locals().get("completed"), "timed_out", False
            )
            return (
                False,
                SubtitleExportFailure(
                    int(stream.index), target.language, codec, reason, str(output)
                ),
                aborted,
            )

    def pgs_fallback(self, input_path, stream, out_file):
        tools = getattr(self.worker, "tools", None)
        mkvmerge = str(getattr(tools, "mkvmerge", "") or "")
        mkvextract = str(getattr(tools, "mkvextract", "") or "")
        if (
            Path(input_path).suffix.casefold() != ".mkv"
            or not mkvmerge
            or not mkvextract
        ):
            return False
        out_file.unlink(missing_ok=True)
        probe = self.run(
            [
                self.ffprobe,
                "-v",
                "error",
                "-select_streams",
                "s",
                "-show_entries",
                "stream=index",
                "-of",
                "json",
                input_path,
            ],
            label="PGS-Fallback ffprobe",
            timeout_s=60,
            worker=self.worker,
            log=self.log,
        )
        identify = self.run(
            [mkvmerge, "-J", input_path],
            label="PGS-Fallback MKV-Inventar",
            timeout_s=60,
            worker=self.worker,
            log=self.log,
        )
        if any(
            result.returncode != 0 or stopped(result, self.worker)
            for result in [probe, identify]
        ):
            return False
        try:
            track_id = resolve_subtitle_track_id(
                probe.stdout, identify.stdout, stream.index
            )
        except (ValueError, TypeError, KeyError, IndexError):
            return False
        result = self.run(
            [mkvextract, input_path, "tracks", f"{track_id}:{out_file}"],
            label="PGS-Sidecar MKVToolNix",
            timeout_s=300,
            worker=self.worker,
            log=self.log,
        )
        return (
            result.returncode in {0, 1}
            and not stopped(result, self.worker)
            and out_file.is_file()
        )
