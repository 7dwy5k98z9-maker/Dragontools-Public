# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..core.lang_codes import lang_iso_tag, sub_codec_to_ext_and_args
from ..rules.subtitle_rules import (
    build_mp4_subtitle_storage_plan,
    compute_subtitle_plan,
    mp4_sidecars_enabled,
)


def dv_subtitle_storage(container: str | None, subtitle_rules: dict | None = None) -> str:
    """Return the Dolby-Vision subtitle storage policy for *container*.

    MKV stores all selected compatible subtitles internally. MP4 follows the
    global policy: either all selected subtitles as Sidecars or a hybrid path
    with text subtitles internal (tx3g/mov_text) and bitmap subtitles external.
    """
    if str(container or "mp4").strip().lower() == "mkv":
        return "internal"
    return "sidecar" if mp4_sidecars_enabled(subtitle_rules) else "hybrid"


@dataclass(frozen=True)
class DVSubtitleJob:
    stream_index: int
    codec: str
    ext: str
    codec_args: tuple[str, ...]
    language: str
    title: str
    forced: bool


@dataclass(frozen=True)
class DVMuxSubtitleTrack:
    path: Path
    stream_index: int
    codec: str
    language: str
    title: str
    forced: bool


class DVSubtitleMuxService:
    """Select and stage subtitle tracks for internal Dolby-Vision MKV muxes."""

    def __init__(self, *, ffmpeg_path: str, subtitle_rules: dict | None, log) -> None:
        self._ffmpeg_path = ffmpeg_path
        self._subtitle_rules = dict(subtitle_rules or {})
        self._log = log

    def build_internal_jobs(
        self,
        media_info,
        file_override: dict | None,
        *,
        preserve_burn_candidate: bool = False,
    ) -> list[DVSubtitleJob]:
        """Resolve the normal subtitle rules for an internal MKV remux.

        A DV remux cannot burn subtitles into the unchanged video. If the
        normal plan chooses a burn-in candidate, that track is therefore kept
        as an internal MKV subtitle instead of being lost.
        """
        plan = compute_subtitle_plan(
            list(getattr(media_info, "subtitle_streams", None) or []),
            audio_streams=list(getattr(media_info, "audio_streams", None) or []),
            file_override=file_override,
            subtitle_rules=self._subtitle_rules,
            container_copy_supported=True,
            media_duration_s=getattr(media_info, "duration_s", None),
        )
        for warning in getattr(plan, "burn_warnings", ()) or ():
            self._log(f"  ⚠️ {warning}", "warn")

        selected = list(plan.keep_streams)
        burn_sub = getattr(plan, "burn_sub", None)
        if (
            preserve_burn_candidate
            and burn_sub is not None
            and all(int(s.index) != int(burn_sub.index) for s in selected)
        ):
            selected.insert(0, burn_sub)
            self._log(
                f"  💬 Sub #{burn_sub.index}: Burn-In ist im DV-MKV-Pfad nicht möglich; "
                "Spur wird intern im MKV erhalten.",
                "info",
            )

        jobs: list[DVSubtitleJob] = []
        seen: set[int] = set()
        for stream in selected:
            stream_index = int(stream.index)
            if stream_index in seen:
                continue
            seen.add(stream_index)

            codec = str(stream.codec or "").lower()
            codec_result = sub_codec_to_ext_and_args(codec)
            if codec_result is None:
                self._log(
                    f"  ⚠️ Sub #{stream_index} ({codec or 'unbekannt'}) kann nicht "
                    "für den internen MKV-Mux aufbereitet werden und wird übersprungen.",
                    "warn",
                )
                continue

            ext, codec_args = codec_result
            jobs.append(
                DVSubtitleJob(
                    stream_index=stream_index,
                    codec=codec,
                    ext=ext,
                    codec_args=tuple(codec_args),
                    language=lang_iso_tag(stream.language or "und"),
                    title=str(stream.title or "").strip(),
                    forced=bool(stream.forced),
                )
            )
        return jobs

    def build_internal_mp4_jobs(
        self,
        media_info,
        file_override: dict | None,
        *,
        preserve_burn_candidate: bool = False,
    ) -> list[DVSubtitleJob]:
        """Bereitet textbasierte MP4-Untertitel für MP4Box als SRT vor.

        MP4Box importiert die SRT-Dateien als Timed Text (tx3g/mov_text).
        PGS/SUP und VobSub werden absichtlich nicht hier aufgenommen; sie
        werden vom Sidecar-Service extern erhalten.
        """
        plan = compute_subtitle_plan(
            list(getattr(media_info, "subtitle_streams", None) or []),
            audio_streams=list(getattr(media_info, "audio_streams", None) or []),
            file_override=file_override,
            subtitle_rules=self._subtitle_rules,
            container_copy_supported=True,
            media_duration_s=getattr(media_info, "duration_s", None),
        )
        storage = build_mp4_subtitle_storage_plan(
            plan,
            subtitle_rules=self._subtitle_rules,
            preserve_burn_candidate=preserve_burn_candidate,
        )
        jobs: list[DVSubtitleJob] = []
        for stream in storage.internal_streams:
            jobs.append(
                DVSubtitleJob(
                    stream_index=int(stream.index),
                    codec=str(stream.codec or "").lower(),
                    ext=".srt",
                    codec_args=("-c:s", "srt"),
                    language=lang_iso_tag(stream.language or "und"),
                    title=str(stream.title or "").strip(),
                    forced=bool(stream.forced),
                )
            )
        return jobs

    def prepare_internal_mp4_tracks(
        self,
        *,
        input_path: str,
        media_info,
        file_override: dict | None,
        tmp_dir: Path,
        run_fn: Callable[[list[str]], int],
        preserve_burn_candidate: bool = False,
    ) -> tuple[bool, list[DVMuxSubtitleTrack]]:
        jobs = self.build_internal_mp4_jobs(
            media_info,
            file_override,
            preserve_burn_candidate=preserve_burn_candidate,
        )
        if not jobs:
            return True, []

        self._log(
            f"  💬 Bereite {len(jobs)} Text-Untertitelspur(en) für internen MP4-Timed-Text-Mux vor ...",
            "info",
        )
        tracks: list[DVMuxSubtitleTrack] = []
        for idx, job in enumerate(jobs):
            output = tmp_dir / f"subtitle_mp4_{idx}.srt"
            cmd = [
                self._ffmpeg_path,
                "-y", "-nostdin", "-loglevel", "error",
                "-i", input_path,
                "-map", f"0:{job.stream_index}",
                "-c:s", "srt",
                "-vn", "-an", "-dn",
                str(output),
            ]
            rc = run_fn(cmd)
            if rc != 0 or not output.exists() or output.stat().st_size <= 0:
                self._log(
                    f"❌ MP4-Untertitel-Aufbereitung fehlgeschlagen (Spur #{job.stream_index}).",
                    "error",
                )
                return False, tracks
            tracks.append(
                DVMuxSubtitleTrack(
                    path=output,
                    stream_index=job.stream_index,
                    codec="mov_text",
                    language=job.language,
                    title=job.title,
                    forced=job.forced,
                )
            )
        return True, tracks

    def prepare_internal_mkv_tracks(
        self,
        *,
        input_path: str,
        media_info,
        file_override: dict | None,
        tmp_dir: Path,
        run_fn: Callable[[list[str]], int],
        preserve_burn_candidate: bool = False,
    ) -> tuple[bool, list[DVMuxSubtitleTrack]]:
        jobs = self.build_internal_jobs(
            media_info,
            file_override,
            preserve_burn_candidate=preserve_burn_candidate,
        )
        if not jobs:
            if getattr(media_info, "subtitle_streams", None):
                self._log("  💬 Keine Untertitelspur gemäß Regelwerk für den MKV-Container ausgewählt.", "info")
            return True, []

        self._log(
            f"  💬 Übernehme {len(jobs)} Untertitelspur(en) intern in den MKV-Container ...",
            "info",
        )
        tracks: list[DVMuxSubtitleTrack] = []
        for idx, job in enumerate(jobs):
            output = tmp_dir / f"subtitle_{idx}{job.ext}"
            cmd = [
                self._ffmpeg_path,
                "-y",
                "-nostdin",
                "-loglevel",
                "error",
                "-i",
                input_path,
                "-map",
                f"0:{job.stream_index}",
                *job.codec_args,
                "-vn",
                "-an",
                "-dn",
                str(output),
            ]
            rc = run_fn(cmd)
            if rc != 0 or not output.exists() or output.stat().st_size <= 0:
                self._log(
                    f"❌ Untertitel-Aufbereitung fehlgeschlagen (Spur #{job.stream_index}).",
                    "error",
                )
                return False, tracks
            tracks.append(
                DVMuxSubtitleTrack(
                    path=output,
                    stream_index=job.stream_index,
                    codec=job.codec,
                    language=job.language,
                    title=job.title,
                    forced=job.forced,
                )
            )
        return True, tracks
