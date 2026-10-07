# -*- coding: utf-8 -*-
"""Final MP4Box/mkvmerge muxing for Dolby Vision remux jobs."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from .dv_mkv_source_subtitles import resolve_subtitle_ids, direct_subtitle_args

from ..core.timeout_settings import get_timeout
from .dv_subtitle_mux_service import DVMuxSubtitleTrack
from .dv_mux_input_validation import required_mux_inputs_available
from .mp4box_track_args import mp4box_track_argument, append_mp4box_subtitle
from .mkv_audio_track_args import mkv_audio_track_args


class DVRemuxMuxer:
    def __init__(self, worker, process_runner):
        self.worker = worker
        self.process_runner = process_runner

    def mux_mp4(
        self,
        video_hevc: str,
        audio_tracks: list[tuple[str, dict]],
        output_path: str,
        subtitle_tracks: list[DVMuxSubtitleTrack] | None = None,
    ) -> bool:
        w = self.worker
        if not required_mux_inputs_available([path for path, _job in audio_tracks] + [track.path for track in subtitle_tracks or ()]):
            w.log("❌ DV-MP4: eine geplante Mux-Spur fehlt oder ist leer.", "error")
            return False
        # MP4 is intentionally a Profile-8.1 compatibility target.  The
        # pipeline guarantees that ``video_hevc`` has actually been prepared
        # with dovi_tool Mode 2 before this explicit container signal is set.
        cmd = [w.tools.mp4box, "-new", output_path, "-add", f"{video_hevc}:dvp=8.1.hdr10"]
        for audio_path, audio_job in audio_tracks:
            lang = (audio_job.get("language") or "und").lower()
            title = (audio_job.get("title") or "").replace('"', "'").strip()
            add_arg = mp4box_track_argument(audio_path, language=lang, title=title,media_type='audio',
                default=audio_job.get('default'))
            cmd += ["-add", add_arg]

        for subtitle_track in list(subtitle_tracks or []):
            append_mp4box_subtitle(cmd, subtitle_track)

        w._last_stderr = ""
        rc, stdout, stderr = self.process_runner.run_abortable_capture(cmd)
        if _abort_current_file(w):
            w.log("MP4Box abgebrochen.", "warn")
            return False
        if rc != 0:
            self._log_mux_error("MP4Box", rc, stdout, stderr)
        return rc == 0 and _nonempty_file(output_path)

    def mux_mkv(
        self,
        video_hevc: str,
        audio_tracks: list[tuple[str, dict]],
        output_path: str,
        subtitle_tracks: list[DVMuxSubtitleTrack] | None = None,
    ) -> bool:
        w = self.worker
        if not required_mux_inputs_available([path for path, _job in audio_tracks] + [track.path for track in subtitle_tracks or ()]):
            w.log("❌ DV-MKV: eine geplante Mux-Spur fehlt oder ist leer.", "error")
            return False
        cmd = [w.tools.mkvmerge, "-o", output_path, video_hevc]
        for audio_path, audio_job in audio_tracks:
            lang = (audio_job.get("language") or "und").lower()
            title = (audio_job.get("title") or "").replace('"', "'").strip()
            cmd += mkv_audio_track_args(audio_path, audio_job, language=lang, title=title)

        source_ids = {}
        for subtitle_track in list(subtitle_tracks or []):
            lang = (subtitle_track.language or "und").lower()
            title = (subtitle_track.title or "").replace('"', "'").strip()
            forced = "yes" if subtitle_track.forced else "no"
            if getattr(subtitle_track, "source_direct", False):
                def capture(command):
                    rc, stdout, stderr = self.process_runner.run_abortable_capture(command, timeout_s=60)
                    return SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr, aborted=_abort_current_file(w))
                try:
                    key = str(subtitle_track.path)
                    if key not in source_ids:
                        source_ids[key] = resolve_subtitle_ids(
                            path=subtitle_track.path, ffprobe=getattr(w.tools, "ffprobe", "ffprobe"),
                            mkvmerge=w.tools.mkvmerge, capture=capture,
                            required_stream_indices={t.stream_index for t in subtitle_tracks if getattr(t, 'source_direct', False) and str(t.path)==key},
                        )
                    track_id = source_ids[key][int(subtitle_track.stream_index)]
                except (ValueError, KeyError, OSError) as exc:
                    w.log(f"❌ PGS-Spurzuordnung fehlgeschlagen: {exc}", "error")
                    return False
                cmd += direct_subtitle_args(subtitle_track, track_id)
                continue
            cmd += direct_subtitle_args(subtitle_track,0)

        w._last_stderr = ""
        rc, stdout, stderr = self.process_runner.run_abortable_capture(
            cmd,
            timeout_s=get_timeout("dv_mkvmerge"),
        )
        if _abort_current_file(w):
            w.log("mkvmerge abgebrochen.", "warn")
            return False
        if rc not in {0, 1}:
            self._log_mux_error("mkvmerge", rc, stdout, stderr)
            return False
        if rc == 1:
            w.log("⚠️ mkvmerge meldete Warnungen; die DV-MKV wird anschließend normal validiert.", "warn")
        return _nonempty_file(output_path)

    def mux(
        self,
        video_hevc: str,
        audio_tracks: list[tuple[str, dict]],
        output_path: str,
        subtitle_tracks: list[DVMuxSubtitleTrack] | None = None,
    ) -> bool:
        container = str(getattr(self.worker, "container", "mp4") or "mp4").lower()
        if container == "mkv":
            return self.mux_mkv(video_hevc, audio_tracks, output_path, subtitle_tracks)
        if container == "mp4":
            return self.mux_mp4(video_hevc, audio_tracks, output_path, subtitle_tracks)
        self.worker.log(f"❌ Ungültiger DV-Container: {container!r}", "error")
        return False

    def _log_mux_error(self, tool: str, rc: int, stdout: str, stderr: str) -> None:
        w = self.worker
        w._last_stderr = "\n".join(
            [
                line
                for line in ((stderr or "") + "\n" + (stdout or "")).splitlines()
                if line.strip()
            ][-10:]
        )
        w.log(f"❌ {tool} fehlgeschlagen (rc={rc})", "error")
        for line in w._last_stderr.splitlines()[-5:]:
            if line.strip():
                w.log(f"  {tool}: {line}", "error")


def _nonempty_file(path: str | Path) -> bool:
    candidate = Path(path)
    return candidate.exists() and candidate.stat().st_size > 0


def _abort_current_file(worker) -> bool:
    return bool(getattr(worker, "abort_requested", False) and getattr(worker, "abort_type", None) == "sofort")
