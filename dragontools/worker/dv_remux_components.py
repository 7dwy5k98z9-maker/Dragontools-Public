# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
import time
import traceback
from pathlib import Path

from ..rules.audio_plan import audio_filter_chain, compute_audio_track_plan
from .output_size_policy import validate_output_size_policy
from ..core.output_replace import commit_staged_output
from ..core.timeout_settings import get_timeout
from ..core.audio_titles import build_audio_title
from .tool_runner import run_tool
from .dv_subtitle_mux_service import (
    DVMuxSubtitleTrack,
    DVSubtitleMuxService,
    dv_subtitle_storage as dv_remux_subtitle_storage,
)



class DVRemuxProcessRunner:
    """Subprocess-Ausführung, Fortschritt und abortable capture für DV-Remux."""

    def __init__(self, worker):
        self.worker = worker

    def run_cmd(self, cmd, input_path=None, dur_ms=None, pct_range: tuple[int, int] = (0, 95)) -> int:
        w = self.worker
        full = cmd + ["-progress", "pipe:1", "-nostats"]
        w._last_stderr = ""
        start = time.time()
        last_out_ms = 0
        last_speed: float | None = None

        def _progress_line(raw_line: str) -> None:
            nonlocal last_out_ms, last_speed
            line = raw_line.strip()
            if not line or "=" not in line:
                return
            k, v = line.split("=", 1)
            if k == "speed":
                try:
                    parsed = float(v.strip().lower().rstrip("x"))
                    if parsed > 0:
                        last_speed = parsed
                except (TypeError, ValueError):
                    return
                return
            if k == "out_time_ms" and dur_ms:
                try:
                    last_out_ms = max(0, int(int(v) / 1000))
                    raw_pct = min(100, int(last_out_ms / dur_ms * 100))
                    pct = pct_range[0] + int(raw_pct * (pct_range[1] - pct_range[0]) / 100)
                    pct = max(pct_range[0], min(pct_range[1], pct))
                    eta_s: float | None = None
                    if last_out_ms > 0:
                        phase_frac = (pct_range[1] - pct_range[0]) / 100.0
                        remaining_ms = max(0.0, dur_ms * phase_frac - last_out_ms)
                        if last_speed and last_speed > 0:
                            eta_s = (remaining_ms / 1000.0) / last_speed
                        else:
                            elapsed = max(0.001, time.time() - start)
                            derived_speed = (last_out_ms / 1000.0) / elapsed
                            if derived_speed > 0:
                                eta_s = (remaining_ms / 1000.0) / derived_speed
                    if input_path:
                        w.file_progress.emit(input_path, pct, eta_s)
                except (TypeError, ValueError, ZeroDivisionError):
                    return

        result = run_tool(
            full,
            label="DV-Remux ffmpeg",
            timeout_s=get_timeout("worker_media_process"),
            timeout_mode="inactivity",
            worker=w,
            log=w._log,
            stdout_line=_progress_line,
        )
        stderr_lines = [line for line in result.stderr.splitlines() if line.strip()]
        w._last_stderr = "\n".join(stderr_lines[-10:])
        if not result.ok:
            tool = Path(cmd[0]).name if cmd else "Tool"
            if result.timed_out:
                w.log(f"❌ {tool}: Inaktivitäts-Timeout", "error")
            elif result.aborted:
                w.log(f"⏹️ {tool}: abgebrochen", "warn")
            else:
                w.log(f"❌ {tool} fehlgeschlagen (rc={result.returncode})", "error")
            for line in stderr_lines[-5:]:
                if line.strip():
                    w.log(f"  {tool}: {line}", "error")
        return result.returncode

    def probe_ms(self, path) -> int | None:
        w = self.worker
        try:
            result = run_tool(
                [
                    w.tools.ffprobe,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    path,
                ],
                label="DV-Remux ffprobe",
                timeout_s=get_timeout("media_analysis"),
                worker=w,
                log=w._log,
            )
            if not result.ok:
                return None
            v = result.stdout.strip()
            return int(float(v) * 1000) if v else None
        except (TypeError, ValueError, OSError):
            return None

    def run_abortable_capture(self, cmd: list[str], *, timeout_s: int | None = None) -> tuple[int, str, str]:
        w = self.worker
        effective_timeout = get_timeout("dv_mp4box") if timeout_s is None else timeout_s
        result = run_tool(
            cmd,
            label="DV-Remux-Prozess",
            timeout_s=effective_timeout,
            worker=w,
            log=w._log,
        )
        return result.returncode, result.stdout, result.stderr


class DVMP4BoxPipelineRunner:
    """DV-Remux-Pipeline: MP4 via MP4Box, MKV via mkvmerge.

    Der historische Klassenname bleibt aus Kompatibilitätsgründen bestehen.
    """

    def __init__(self, worker, process_runner: DVRemuxProcessRunner):
        self.worker = worker
        self.process_runner = process_runner
        self.audio_pct_range = (55, 80)
        self._subtitle_mux_service = DVSubtitleMuxService(
            ffmpeg_path=getattr(getattr(worker, "tools", None), "ffmpeg", "ffmpeg"),
            subtitle_rules=getattr(worker, "subtitle_rules", None),
            log=worker.log,
        )

    def build_audio_jobs(self, mi, file_override: dict | None) -> list[dict]:
        w = self.worker
        container = str(getattr(w, "container", "mp4") or "mp4").lower()
        plan = compute_audio_track_plan(
            audio_streams=mi.audio_streams,
            file_override=file_override,
            container=container,
        )
        jobs: list[dict] = []
        for decision in plan:
            chosen = decision.stream
            if decision.needs_transcode:
                codec = decision.target_codec
                bitrate_k = max(1, int(decision.target_bitrate / 1000) if decision.target_bitrate else 256)
                ext = ".mka" if container == "mkv" else (".eac3" if codec == "eac3" else (".ac3" if codec == "ac3" else ".m4a"))
                w.log(f"  🔊 Audio #{chosen.index} ({chosen.codec}) -> {codec} {decision.target_channels}ch {bitrate_k}k", "info")
                jobs.append({
                    "stream_index": chosen.index,
                    "mode": "transcode",
                    "codec": codec,
                    "channels": decision.target_channels,
                    "bitrate_k": bitrate_k,
                    "filter_chain": audio_filter_chain(decision),
                    "drc_scale": decision.drc_scale,
                    "ext": ext,
                    "language": (chosen.language or "und").lower(),
                    "title": build_audio_title(
                        language=chosen.language, codec=codec,
                        channels=decision.target_channels, bitrate_bps=decision.target_bitrate,
                    ),
                })
            else:
                cn = decision.target_codec
                ext = ".mka" if container == "mkv" else (".eac3" if cn == "eac3" else (".ac3" if cn == "ac3" else ".m4a"))
                w.log(f"  🔊 Audio #{chosen.index} ({chosen.codec}) -> copy", "info")
                jobs.append({
                    "stream_index": chosen.index,
                    "mode": "copy",
                    "codec": cn,
                    "ext": ext,
                    "language": (chosen.language or "und").lower(),
                    "title": build_audio_title(
                        language=chosen.language, codec=cn,
                        channels=decision.target_channels, bitrate_bps=decision.target_bitrate,
                    ),
                })
        return jobs

    def extract_video(self, input_path: str, output_hevc: str, dur_ms: int | None) -> bool:
        w = self.worker
        cmd = [
            w.tools.ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-i",
            input_path,
            "-map",
            "0:v:0",
            "-c:v",
            "copy",
            "-bsf:v",
            "hevc_mp4toannexb",
            "-an",
            "-sn",
            "-dn",
            "-f",
            "hevc",
            output_hevc,
        ]
        rc = self.process_runner.run_cmd(cmd, input_path, dur_ms, pct_range=(0, 55))
        return rc == 0 and Path(output_hevc).exists() and Path(output_hevc).stat().st_size > 0

    def extract_audio(self, input_path: str, audio_job: dict, output_audio: str, dur_ms: int | None) -> bool:
        w = self.worker
        cmd = [w.tools.ffmpeg, "-y", "-loglevel", "error"]
        if audio_job.get("drc_scale") is not None:
            cmd += ["-drc_scale", f"{float(audio_job['drc_scale']):.1f}"]
        cmd += ["-i", input_path, "-map", f"0:{audio_job['stream_index']}"]
        if audio_job["mode"] == "copy":
            cmd += ["-c:a", "copy"]
        else:
            cmd += ["-c:a", audio_job["codec"], "-ac", str(audio_job["channels"]), "-b:a", f"{audio_job['bitrate_k']}k"]
            if audio_job.get("filter_chain"):
                cmd += ["-filter:a", str(audio_job["filter_chain"])]
        cmd += ["-vn", "-sn", "-dn"]
        if str(getattr(w, "container", "mp4") or "mp4").lower() == "mkv":
            # Eine einspurige MKA-Zwischendatei ist codec-agnostisch und kann
            # TrueHD/DTS/FLAC/AAC usw. verlustfrei an mkvmerge übergeben.
            cmd += ["-f", "matroska"]
        cmd += [output_audio]
        rc = self.process_runner.run_cmd(cmd, input_path, dur_ms, pct_range=self.audio_pct_range)
        return rc == 0 and Path(output_audio).exists() and Path(output_audio).stat().st_size > 0

    def _mux_mp4(
        self,
        video_hevc: str,
        audio_tracks: list[tuple[str, dict]],
        output_path: str,
        subtitle_tracks: list[DVMuxSubtitleTrack] | None = None,
    ) -> bool:
        w = self.worker
        cmd = [w.tools.mp4box, "-new", output_path, "-add", f"{video_hevc}:dvp=8.1.hdr10"]
        for audio_path, audio_job in audio_tracks:
            if not (Path(audio_path).exists() and Path(audio_path).stat().st_size > 0):
                continue
            lang = (audio_job.get("language") or "und").lower()
            title = (audio_job.get("title") or "").replace('"', "'").strip()
            add_arg = f"{audio_path}:lang={lang}"
            if title:
                add_arg += f':name="{title}"'
            cmd += ["-add", add_arg]

        for subtitle_track in list(subtitle_tracks or []):
            if not (subtitle_track.path.exists() and subtitle_track.path.stat().st_size > 0):
                continue
            lang = (subtitle_track.language or "und").lower()
            title = (subtitle_track.title or "").replace('"', "'").strip()
            if subtitle_track.forced and "forced" not in title.lower():
                title = f"{title} [Forced]".strip() if title else "Forced"
            add_arg = f"{subtitle_track.path}:lang={lang}"
            if title:
                add_arg += f':name="{title}"'
            cmd += ["-add", add_arg]

        w._last_stderr = ""
        rc, stdout, stderr = self.process_runner.run_abortable_capture(cmd)
        if w.abort_requested:
            w.log("MP4Box abgebrochen.", "warn")
            return False
        if rc != 0:
            w._last_stderr = "\n".join(
                [line for line in ((stderr or "") + "\n" + (stdout or "")).splitlines() if line.strip()][-10:]
            )
            w.log(f"❌ MP4Box fehlgeschlagen (rc={rc})", "error")
            for line in w._last_stderr.splitlines()[-5:]:
                if line.strip():
                    w.log(f"  MP4Box: {line}", "error")
        return rc == 0 and Path(output_path).exists() and Path(output_path).stat().st_size > 0

    def _mux_mkv(
        self,
        video_hevc: str,
        audio_tracks: list[tuple[str, dict]],
        output_path: str,
        subtitle_tracks: list[DVMuxSubtitleTrack] | None = None,
    ) -> bool:
        w = self.worker
        cmd = [w.tools.mkvmerge, "-o", output_path, video_hevc]
        for audio_path, audio_job in audio_tracks:
            if not (Path(audio_path).exists() and Path(audio_path).stat().st_size > 0):
                continue
            lang = (audio_job.get("language") or "und").lower()
            title = (audio_job.get("title") or "").replace('"', "'").strip()
            cmd += ["--language", f"0:{lang}"]
            if title:
                cmd += ["--track-name", f"0:{title}"]
            cmd += [audio_path]

        for subtitle_track in list(subtitle_tracks or []):
            if not (subtitle_track.path.exists() and subtitle_track.path.stat().st_size > 0):
                continue
            lang = (subtitle_track.language or "und").lower()
            title = (subtitle_track.title or "").replace('"', "'").strip()
            forced = "yes" if subtitle_track.forced else "no"
            cmd += ["--language", f"0:{lang}", "--forced-display-flag", f"0:{forced}"]
            if title:
                cmd += ["--track-name", f"0:{title}"]
            cmd += [str(subtitle_track.path)]

        w._last_stderr = ""
        rc, stdout, stderr = self.process_runner.run_abortable_capture(
            cmd, timeout_s=get_timeout("dv_mkvmerge")
        )
        if w.abort_requested:
            w.log("mkvmerge abgebrochen.", "warn")
            return False
        # mkvmerge: 0=Erfolg, 1=Erfolg mit Warnungen, 2=Fehler.
        if rc not in {0, 1}:
            w._last_stderr = "\n".join(
                [line for line in ((stderr or "") + "\n" + (stdout or "")).splitlines() if line.strip()][-10:]
            )
            w.log(f"❌ mkvmerge fehlgeschlagen (rc={rc})", "error")
            for line in w._last_stderr.splitlines()[-5:]:
                if line.strip():
                    w.log(f"  mkvmerge: {line}", "error")
            return False
        if rc == 1:
            w.log("⚠️ mkvmerge meldete Warnungen; die DV-MKV wird anschließend normal validiert.", "warn")
        return Path(output_path).exists() and Path(output_path).stat().st_size > 0

    def mux(
        self,
        video_hevc: str,
        audio_tracks: list[tuple[str, dict]],
        output_path: str,
        subtitle_tracks: list[DVMuxSubtitleTrack] | None = None,
    ) -> bool:
        container = str(getattr(self.worker, "container", "mp4") or "mp4").lower()
        if container == "mkv":
            return self._mux_mkv(video_hevc, audio_tracks, output_path, subtitle_tracks)
        return self._mux_mp4(video_hevc, audio_tracks, output_path, subtitle_tracks)

    def run(self, input_path: str, output_path: str, mi, dur_ms: int | None, file_override: dict | None, name: str) -> bool:
        w = self.worker
        with tempfile.TemporaryDirectory(prefix="dragontools_dv_remux_") as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            raw_video = tmp_dir / "video.hevc"
            audio_jobs = self.build_audio_jobs(mi, file_override)
            audio_tracks: list[tuple[str, dict]] = []

            container = str(getattr(w, "container", "mp4") or "mp4").lower()
            subtitle_tracks: list[DVMuxSubtitleTrack] = []
            muxer_name = "mkvmerge" if container == "mkv" else "MP4Box"
            w.log(f"  🎞️ Extrahiere DV-Videostream für {muxer_name} ...", "info")
            if not self.extract_video(input_path, str(raw_video), dur_ms):
                w.log(f"❌ Video-Extraktion fehlgeschlagen: {name}", "error")
                return False
            if w.abort_requested:
                return False

            if audio_jobs:
                for idx, job in enumerate(audio_jobs):
                    total = max(1, len(audio_jobs))
                    self.audio_pct_range = (
                        55 + int(idx / total * 25),
                        55 + int((idx + 1) / total * 25),
                    )
                    audio_path = tmp_dir / f"audio_{idx}{job['ext']}"
                    if not self.extract_audio(input_path, job, str(audio_path), dur_ms):
                        w.log(f"❌ Audio-Aufbereitung fehlgeschlagen (Spur #{job['stream_index']}): {name}", "error")
                        return False
                    if w.abort_requested:
                        return False
                    audio_tracks.append((str(audio_path), job))
            else:
                w.log(f"  🔇 Keine passende Audiospur gefunden - {container.upper()} wird ohne Audio erstellt.", "warn")

            storage_mode = dv_remux_subtitle_storage(container, getattr(w, "subtitle_rules", None))
            if container == "mkv":
                ok_subs, subtitle_tracks = self._subtitle_mux_service.prepare_internal_mkv_tracks(
                    input_path=input_path,
                    media_info=mi,
                    file_override=file_override,
                    tmp_dir=tmp_dir,
                    run_fn=lambda cmd: self.process_runner.run_cmd(
                        cmd, input_path, dur_ms, pct_range=(80, 82)
                    ),
                    preserve_burn_candidate=True,
                )
                if not ok_subs or w.abort_requested:
                    return False
            elif storage_mode == "hybrid":
                ok_subs, subtitle_tracks = self._subtitle_mux_service.prepare_internal_mp4_tracks(
                    input_path=input_path,
                    media_info=mi,
                    file_override=file_override,
                    tmp_dir=tmp_dir,
                    run_fn=lambda cmd: self.process_runner.run_cmd(
                        cmd, input_path, dur_ms, pct_range=(80, 82)
                    ),
                    preserve_burn_candidate=True,
                )
                if not ok_subs or w.abort_requested:
                    return False

            w.log(f"  📦 Erstelle finale DV-{container.upper()} mit {muxer_name} ...", "info")
            w.file_progress.emit(input_path, 82, None)
            if w.abort_requested:
                return False
            return self.mux(str(raw_video), audio_tracks, output_path, subtitle_tracks) and not w.abort_requested


class DVOutputManager:
    """Output-Pfad, Replacement und Cleanup für DV-Remux."""

    def __init__(self, worker):
        self.worker = worker
        self._archiviert: int = 0

    @property
    def archiviert(self) -> int:
        """Anzahl der DV-Ausgaben, die wegen Größenregel in Archiv/ abgelegt wurden."""
        return self._archiviert

    def build_output_path(self, input_path: str) -> str:
        w = self.worker
        stem = Path(input_path).stem
        base_dir = Path(input_path).parent
        if w.overwrite_original:
            tmp_dir = base_dir / "__temp_dv_remux__"
            tmp_dir.mkdir(exist_ok=True)
            return str(tmp_dir / f"{stem}.{w.container}")
        candidate = base_dir / f"{stem}_DV_Remux.{w.container}"
        counter = 1
        while candidate.exists():
            candidate = base_dir / f"{stem}_DV_Remux_{counter}.{w.container}"
            counter += 1
        return str(candidate)

    def replace_output_if_needed(self, input_path: str, output_path: str) -> tuple[bool, str]:
        w = self.worker

        # ── Größenregel prüfen (beide Modi: overwrite und nicht-overwrite) ──
        allowed, preserved_path = validate_output_size_policy(
            input_path=input_path,
            output_path=output_path,
            logger=w._log,
        )
        if not allowed:
            if preserved_path is not None:
                self._archiviert += 1
                w.log(
                    f"📦 DV-Ausgabe wegen Größenregel in Archiv/ abgelegt: {preserved_path.name}",
                    "warn",
                )
            else:
                w.log(
                    "⚠️ DV-Ausgabe wegen Größenregel verworfen (Archivierung fehlgeschlagen).",
                    "warn",
                )
            # Temp-Verzeichnis aufräumen (Datei wurde bereits durch validate_output_size_policy verschoben)
            self.cleanup_temp_dir(input_path)
            return False, str(preserved_path or output_path)

        if not w.overwrite_original:
            return True, output_path

        final_path = Path(input_path).with_suffix(f".{w.container}")
        replace_ok = False
        try:
            out_p = Path(output_path)
            if not out_p.exists() or out_p.stat().st_size < 1024:
                raise RuntimeError(f"Temporäre DV-Ausgabedatei fehlt oder unplausibel klein: {out_p.name}")

            input_p = Path(input_path)
            final_resolved = final_path.resolve()
            if final_path.exists():
                input_resolved = input_p.resolve()
                out_resolved = out_p.resolve()
                if final_resolved != input_resolved and final_resolved != out_resolved:
                    raise RuntimeError(f"Zieldatei existiert bereits und wird nicht überschrieben: {final_path.name}")

            result = commit_staged_output(
                source=input_p,
                staging=out_p,
                destination=final_path,
                log=w.log,
                min_size=1024,
            )
            output_path = str(result.destination)
            replace_ok = True
        except Exception as e:
            w.log(f"Ersetzen fehlgeschlagen: {e}", "error")
            w.log(traceback.format_exc(), "error")
        finally:
            self.cleanup_temp_dir(input_path)
        return replace_ok, output_path

    def cleanup_temp_dir(self, input_path: str) -> None:
        temp_dir = Path(input_path).parent / "__temp_dv_remux__"
        try:
            temp_dir.rmdir()
        except FileNotFoundError:
            return
        except OSError as exc:
            if temp_dir.exists():
                self.worker.log(
                    f"Temporärer DV-Remux-Ordner konnte nicht entfernt werden: {temp_dir.name} - {exc}",
                    "warn",
                )

    def cleanup_incomplete(self, input_path: str, output_path: str | None) -> None:
        w = self.worker
        if output_path:
            out_p = Path(output_path)
            if out_p.exists():
                try:
                    out_p.unlink()
                except Exception as e:
                    w.log(f"Unvollständige DV-Ausgabedatei konnte nicht gelöscht werden: {out_p.name} - {e}", "warn")
        self.cleanup_temp_dir(input_path)
