# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Callable

from .dv_mkv_source_subtitles import resolve_subtitle_ids, direct_subtitle_args
from .dv_mux_input_validation import required_mux_inputs_available
from .mkv_audio_track_args import mkv_audio_track_args


class DVMKVMuxer:
    """Finaler Matroska-Mux für bereits injizierte HEVC-DV-Bitstreams."""

    def __init__(self, *, mkvmerge_path: str, audio_track_name: Callable[[dict], str], ffprobe_path: str = "ffprobe", log=None) -> None:
        self._mkvmerge_path = mkvmerge_path
        self._audio_track_name = audio_track_name
        self._ffprobe_path = ffprobe_path
        self._log = log or (lambda *_: None)

    def mux_final_output(
        self,
        run_fn,
        *,
        output_path: str,
        injected_hevc: Path,
        mux_tracks,
        subtitle_tracks=(),
    ) -> bool:
        mux_tracks = list(mux_tracks)
        subtitle_tracks = list(subtitle_tracks or ())
        if not required_mux_inputs_available(track.path for track in [*mux_tracks, *subtitle_tracks]):
            self._log("❌ DV-MKV: eine geplante Mux-Spur fehlt oder ist leer.", "error")
            return False
        cmd = [self._mkvmerge_path, "-o", output_path, str(injected_hevc)]
        for track in mux_tracks:
            meta = track.meta or {}
            lang = str(meta.get("lang") or "und").strip().lower()
            title = self._audio_track_name(meta)
            cmd += mkv_audio_track_args(track.path, meta, language=lang, title=title)
        source_ids = {}
        for track in subtitle_tracks or ():
            if getattr(track, "source_direct", False):
                try:
                    key = str(track.path)
                    if key not in source_ids:
                        source_ids[key] = resolve_subtitle_ids(
                            path=track.path, ffprobe=self._ffprobe_path, mkvmerge=self._mkvmerge_path,
                            required_stream_indices={t.stream_index for t in subtitle_tracks if getattr(t, 'source_direct', False) and str(t.path)==key},
                            capture=lambda command: run_fn(
                                command, return_process=True, timeout=60, label="PGS-Quellenanalyse",
                            ),
                        )
                    track_id = source_ids[key][int(track.stream_index)]
                except (ValueError, KeyError, OSError) as exc:
                    self._log(f"❌ PGS-Spurzuordnung fehlgeschlagen: {exc}", "error")
                    return False
                cmd += direct_subtitle_args(track, track_id)
                continue
            cmd += direct_subtitle_args(track,0)
        rc = run_fn(cmd)
        out = Path(output_path)
        if rc == 1:
            self._log("⚠️ mkvmerge meldete Warnungen; Ausgabe wird anschließend validiert.", "warn")
        return rc in {0, 1} and out.exists() and out.stat().st_size > 0
