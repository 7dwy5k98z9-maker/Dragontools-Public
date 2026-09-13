# -*- coding: utf-8 -*-
"""Final MP4Box/mkvmerge muxing for Dolby Vision remux jobs."""
from __future__ import annotations

from pathlib import Path

from ..core.timeout_settings import get_timeout
from .dv_subtitle_mux_service import DVMuxSubtitleTrack


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
        cmd = [w.tools.mp4box, "-new", output_path, "-add", f"{video_hevc}:dvp=8.1.hdr10"]
        for audio_path, audio_job in audio_tracks:
            if not _nonempty_file(audio_path):
                continue
            lang = (audio_job.get("language") or "und").lower()
            title = (audio_job.get("title") or "").replace('"', "'").strip()
            add_arg = f"{audio_path}:lang={lang}"
            if title:
                add_arg += f':name="{title}"'
            cmd += ["-add", add_arg]

        for subtitle_track in list(subtitle_tracks or []):
            if not _nonempty_file(subtitle_track.path):
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
        cmd = [w.tools.mkvmerge, "-o", output_path, video_hevc]
        for audio_path, audio_job in audio_tracks:
            if not _nonempty_file(audio_path):
                continue
            lang = (audio_job.get("language") or "und").lower()
            title = (audio_job.get("title") or "").replace('"', "'").strip()
            cmd += ["--language", f"0:{lang}"]
            if title:
                cmd += ["--track-name", f"0:{title}"]
            cmd += [audio_path]

        for subtitle_track in list(subtitle_tracks or []):
            if not _nonempty_file(subtitle_track.path):
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
            cmd,
            timeout_s=get_timeout("dv_mkvmerge"),
        )
        if w.abort_requested:
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
        return self.mux_mp4(video_hevc, audio_tracks, output_path, subtitle_tracks)

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
