# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Callable
from .dv_mux_input_validation import required_mux_inputs_available
from .mp4box_track_args import mp4box_track_argument, append_mp4box_subtitle


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

            add_arg = mp4box_track_argument(af, language=meta.get('lang'), media_type='audio',
                title=self._audio_track_name(meta), default=meta.get('default'))
            mp4_cmd += ["-add", add_arg]


    @staticmethod
    def add_subtitle_tracks(mp4_cmd: list[str], subtitle_tracks) -> None:
        """Fügt vorbereitete SRT-Tracks hinzu; MP4Box wandelt sie in tx3g um."""
        for track in subtitle_tracks or ():
            path = track.path
            if not (path.exists() and path.stat().st_size > 0):
                continue
            append_mp4box_subtitle(mp4_cmd, track)

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
        mux_tracks = list(mux_tracks)
        subtitle_tracks = list(subtitle_tracks or ())
        if not required_mux_inputs_available(track.path for track in [*mux_tracks, *subtitle_tracks]):
            return False
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
