# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Callable


class DVMP4BoxMuxer:
    def __init__(self, *, mp4box_path: str, audio_track_name: Callable[[dict], str]) -> None:
        self._mp4box_path = mp4box_path
        self._audio_track_name = audio_track_name

    def add_audio_tracks(self, mp4_cmd: list[str], mux_tracks) -> None:
        for track in mux_tracks:
            af = track.path
            meta = track.meta
            if not (af.exists() and af.stat().st_size > 0):
                continue

            lang = (meta.get("lang") or "und").lower()
            title = self._audio_track_name(meta)
            safe_title = title.replace('"', "'") if title else ""

            add_arg = f"{af}:lang={lang}"
            if safe_title:
                add_arg += f':name="{safe_title}"'

            mp4_cmd += ["-add", add_arg]


    @staticmethod
    def add_subtitle_tracks(mp4_cmd: list[str], subtitle_tracks) -> None:
        """Fügt vorbereitete SRT-Tracks hinzu; MP4Box wandelt sie in tx3g um."""
        for track in subtitle_tracks or ():
            path = track.path
            if not (path.exists() and path.stat().st_size > 0):
                continue
            lang = str(track.language or "und").strip().lower()
            title = str(track.title or "").replace('"', "'").strip()
            if bool(getattr(track, "forced", False)) and "forced" not in title.lower():
                title = f"{title} [Forced]".strip() if title else "Forced"
            add_arg = f"{path}:lang={lang}"
            if title:
                add_arg += f':name="{title}"'
            mp4_cmd += ["-add", add_arg]

    def mux_plain_mp4_without_dv(
        self,
        run_fn,
        *,
        plain_mp4,
        enc_hevc,
        mux_tracks,
    ) -> bool:
        mp4_cmd = [self._mp4box_path, "-new", str(plain_mp4), "-inter", "500", "-add", str(enc_hevc)]
        self.add_audio_tracks(mp4_cmd, mux_tracks)
        rc = run_fn(mp4_cmd, allow_error=True)
        return rc == 0 and plain_mp4.exists() and plain_mp4.stat().st_size > 0

    def mux_final_output(
        self,
        run_fn,
        *,
        output_path: str,
        injected_hevc,
        mux_tracks,
        subtitle_tracks=(),
    ) -> bool:
        mp4_cmd = [
            self._mp4box_path,
            "-new",
            output_path,
            "-inter", "500",
            "-add",
            f"{injected_hevc}:dvp=8.1.hdr10",
        ]
        self.add_audio_tracks(mp4_cmd, mux_tracks)
        self.add_subtitle_tracks(mp4_cmd, subtitle_tracks)
        return run_fn(mp4_cmd) == 0
