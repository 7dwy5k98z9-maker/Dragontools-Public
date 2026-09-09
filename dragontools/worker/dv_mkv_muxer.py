# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Callable


class DVMKVMuxer:
    """Finaler Matroska-Mux für bereits injizierte HEVC-DV-Bitstreams."""

    def __init__(self, *, mkvmerge_path: str, audio_track_name: Callable[[dict], str]) -> None:
        self._mkvmerge_path = mkvmerge_path
        self._audio_track_name = audio_track_name

    def mux_final_output(
        self,
        run_fn,
        *,
        output_path: str,
        injected_hevc: Path,
        mux_tracks,
        subtitle_tracks=(),
    ) -> bool:
        cmd = [self._mkvmerge_path, "-o", output_path, str(injected_hevc)]
        for track in mux_tracks:
            if not (track.path.exists() and track.path.stat().st_size > 0):
                continue
            meta = track.meta or {}
            lang = str(meta.get("lang") or "und").strip().lower()
            title = self._audio_track_name(meta)
            cmd += ["--language", f"0:{lang}"]
            if title:
                cmd += ["--track-name", f"0:{title}"]
            cmd += [str(track.path)]
        for track in subtitle_tracks or ():
            if not (track.path.exists() and track.path.stat().st_size > 0):
                continue
            lang = str(track.language or "und").strip().lower()
            title = str(track.title or "").replace('"', "'").strip()
            forced = "yes" if bool(track.forced) else "no"
            cmd += ["--language", f"0:{lang}", "--forced-display-flag", f"0:{forced}"]
            if title:
                cmd += ["--track-name", f"0:{title}"]
            cmd += [str(track.path)]
        rc = run_fn(cmd)
        out = Path(output_path)
        return rc == 0 and out.exists() and out.stat().st_size > 0
