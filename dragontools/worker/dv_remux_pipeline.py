# -*- coding: utf-8 -*-
"""Orchestration of the DV remux extraction and final muxing pipeline."""
from __future__ import annotations

import tempfile
from pathlib import Path

from .dv_remux_audio import build_dv_audio_jobs
from .dv_remux_muxers import DVRemuxMuxer
from .dv_subtitle_mux_service import (
    DVMuxSubtitleTrack,
    DVSubtitleMuxService,
    dv_subtitle_storage,
)


class DVRemuxPipelineRunner:
    """Extract DV video/audio/subtitles and build the final MP4 or MKV."""

    def __init__(
        self,
        worker,
        process_runner,
        *,
        audio_plan_builder,
        audio_title_builder,
        audio_filter_builder,
    ):
        self.worker = worker
        self.process_runner = process_runner
        self._audio_plan_builder = audio_plan_builder
        self._audio_title_builder = audio_title_builder
        self._audio_filter_builder = audio_filter_builder
        self.audio_pct_range = (55, 80)
        self._subtitle_mux_service = DVSubtitleMuxService(
            ffmpeg_path=getattr(getattr(worker, "tools", None), "ffmpeg", "ffmpeg"),
            subtitle_rules=getattr(worker, "subtitle_rules", None),
            log=worker.log,
        )
        self._muxer = DVRemuxMuxer(worker, process_runner)

    def build_audio_jobs(self, media_info, file_override: dict | None) -> list[dict]:
        return build_dv_audio_jobs(
            self.worker,
            media_info,
            file_override,
            plan_builder=self._audio_plan_builder,
            title_builder=self._audio_title_builder,
            filter_builder=self._audio_filter_builder,
        )

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
        return rc == 0 and _nonempty_file(output_hevc)

    def extract_audio(
        self,
        input_path: str,
        audio_job: dict,
        output_audio: str,
        dur_ms: int | None,
    ) -> bool:
        w = self.worker
        cmd = [w.tools.ffmpeg, "-y", "-loglevel", "error"]
        if audio_job.get("drc_scale") is not None:
            cmd += ["-drc_scale", f"{float(audio_job['drc_scale']):.1f}"]
        cmd += ["-i", input_path, "-map", f"0:{audio_job['stream_index']}"]
        if audio_job["mode"] == "copy":
            cmd += ["-c:a", "copy"]
        else:
            cmd += [
                "-c:a",
                audio_job["codec"],
                "-ac",
                str(audio_job["channels"]),
                "-b:a",
                f"{audio_job['bitrate_k']}k",
            ]
            if audio_job.get("filter_chain"):
                cmd += ["-filter:a", str(audio_job["filter_chain"])]
        cmd += ["-vn", "-sn", "-dn"]
        if _container(w) == "mkv":
            cmd += ["-f", "matroska"]
        cmd += [output_audio]
        rc = self.process_runner.run_cmd(
            cmd,
            input_path,
            dur_ms,
            pct_range=self.audio_pct_range,
        )
        return rc == 0 and _nonempty_file(output_audio)

    # Compatibility surface retained for existing tests/extensions.
    def _mux_mp4(
        self,
        video_hevc: str,
        audio_tracks: list[tuple[str, dict]],
        output_path: str,
        subtitle_tracks: list[DVMuxSubtitleTrack] | None = None,
    ) -> bool:
        return self._muxer.mux_mp4(video_hevc, audio_tracks, output_path, subtitle_tracks)

    def _mux_mkv(
        self,
        video_hevc: str,
        audio_tracks: list[tuple[str, dict]],
        output_path: str,
        subtitle_tracks: list[DVMuxSubtitleTrack] | None = None,
    ) -> bool:
        return self._muxer.mux_mkv(video_hevc, audio_tracks, output_path, subtitle_tracks)

    def mux(
        self,
        video_hevc: str,
        audio_tracks: list[tuple[str, dict]],
        output_path: str,
        subtitle_tracks: list[DVMuxSubtitleTrack] | None = None,
    ) -> bool:
        return self._muxer.mux(video_hevc, audio_tracks, output_path, subtitle_tracks)

    def run(
        self,
        input_path: str,
        output_path: str,
        mi,
        dur_ms: int | None,
        file_override: dict | None,
        name: str,
    ) -> bool:
        with tempfile.TemporaryDirectory(prefix="dragontools_dv_remux_") as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            raw_video = tmp_dir / "video.hevc"
            audio_jobs = self.build_audio_jobs(mi, file_override)
            audio_tracks: list[tuple[str, dict]] = []
            container = _container(self.worker)
            muxer_name = "mkvmerge" if container == "mkv" else "MP4Box"

            self.worker.log(f"  🎞️ Extrahiere DV-Videostream für {muxer_name} ...", "info")
            if not self.extract_video(input_path, str(raw_video), dur_ms):
                self.worker.log(f"❌ Video-Extraktion fehlgeschlagen: {name}", "error")
                return False
            if self.worker.abort_requested:
                return False

            if not self._prepare_audio_tracks(
                input_path,
                tmp_dir,
                audio_jobs,
                audio_tracks,
                dur_ms,
                name,
            ):
                return False

            ok_subs, subtitle_tracks = self._prepare_subtitles(
                input_path,
                tmp_dir,
                mi,
                file_override,
                dur_ms,
                container,
            )
            if not ok_subs or self.worker.abort_requested:
                return False

            self.worker.log(
                f"  📦 Erstelle finale DV-{container.upper()} mit {muxer_name} ...",
                "info",
            )
            self.worker.file_progress.emit(input_path, 82, None)
            if self.worker.abort_requested:
                return False
            return self.mux(
                str(raw_video),
                audio_tracks,
                output_path,
                subtitle_tracks,
            ) and not self.worker.abort_requested

    def _prepare_audio_tracks(
        self,
        input_path: str,
        tmp_dir: Path,
        audio_jobs: list[dict],
        audio_tracks: list[tuple[str, dict]],
        dur_ms: int | None,
        name: str,
    ) -> bool:
        if not audio_jobs:
            self.worker.log(
                f"  🔇 Keine passende Audiospur gefunden - {_container(self.worker).upper()} wird ohne Audio erstellt.",
                "warn",
            )
            return True

        total = len(audio_jobs)
        for idx, job in enumerate(audio_jobs):
            self.audio_pct_range = (
                55 + int(idx / total * 25),
                55 + int((idx + 1) / total * 25),
            )
            audio_path = tmp_dir / f"audio_{idx}{job['ext']}"
            if not self.extract_audio(input_path, job, str(audio_path), dur_ms):
                self.worker.log(
                    f"❌ Audio-Aufbereitung fehlgeschlagen (Spur #{job['stream_index']}): {name}",
                    "error",
                )
                return False
            if self.worker.abort_requested:
                return False
            audio_tracks.append((str(audio_path), job))
        return True

    def _prepare_subtitles(
        self,
        input_path: str,
        tmp_dir: Path,
        media_info,
        file_override: dict | None,
        dur_ms: int | None,
        container: str,
    ) -> tuple[bool, list[DVMuxSubtitleTrack]]:
        storage_mode = dv_subtitle_storage(
            container,
            getattr(self.worker, "subtitle_rules", None),
        )
        if container == "mkv":
            return self._subtitle_mux_service.prepare_internal_mkv_tracks(
                input_path=input_path,
                media_info=media_info,
                file_override=file_override,
                tmp_dir=tmp_dir,
                run_fn=lambda cmd: self.process_runner.run_cmd(
                    cmd,
                    input_path,
                    dur_ms,
                    pct_range=(80, 82),
                ),
                preserve_burn_candidate=True,
            )
        if storage_mode == "hybrid":
            return self._subtitle_mux_service.prepare_internal_mp4_tracks(
                input_path=input_path,
                media_info=media_info,
                file_override=file_override,
                tmp_dir=tmp_dir,
                run_fn=lambda cmd: self.process_runner.run_cmd(
                    cmd,
                    input_path,
                    dur_ms,
                    pct_range=(80, 82),
                ),
                preserve_burn_candidate=True,
            )
        return True, []


def _container(worker) -> str:
    return str(getattr(worker, "container", "mp4") or "mp4").lower()


def _nonempty_file(path: str | Path) -> bool:
    candidate = Path(path)
    return candidate.exists() and candidate.stat().st_size > 0
