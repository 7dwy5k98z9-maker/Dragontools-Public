# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..core.audio_titles import build_audio_title


@dataclass(frozen=True)
class DVExtractedAudioTrack:
    mux_order: int
    stream_index: int
    codec_name: str
    path: Path


@dataclass(frozen=True)
class DVMuxAudioTrack:
    mux_order: int
    path: Path
    meta: dict


class DVAudioMuxService:
    def __init__(self, *, ffmpeg_path: str, ffprobe_path: str, mp4box_muxer, log) -> None:
        self._ffmpeg_path = ffmpeg_path
        self._ffprobe_path = ffprobe_path
        self._mp4box_muxer = mp4box_muxer
        self._log = log

    def build_audio_meta(self, mi, ov: dict, container: str) -> list[dict]:
        from ..rules.audio_plan import compute_audio_track_plan

        plan = compute_audio_track_plan(
            audio_streams=mi.audio_streams,
            file_override=ov,
            container=container,
        )

        meta: list[dict] = []
        for decision in plan:
            chosen = decision.stream
            meta.append(
                {
                    "mux_order": decision.out_idx,
                    "lang": (getattr(chosen, "language", None) or "und").lower(),
                    "orig_title": getattr(chosen, "title", None) or "",
                    "copied": not decision.needs_transcode,
                    "target_codec": decision.target_codec,
                    "target_channels": decision.target_channels,
                    "target_bitrate": decision.target_bitrate,
                    "source_codec": getattr(chosen, "codec", ""),
                    "source_channels": getattr(chosen, "channels", 0),
                    "source_bitrate": getattr(chosen, "bitrate", 0),
                }
            )

        return meta

    def audio_track_name(self, meta: dict) -> str:
        copied = bool(meta.get("copied"))
        return build_audio_title(
            language=meta.get("lang"),
            codec=(meta.get("source_codec") if copied else meta.get("target_codec")),
            channels=(meta.get("source_channels") if copied else meta.get("target_channels")),
            bitrate_bps=(meta.get("source_bitrate") if copied else meta.get("target_bitrate")),
        )

    def resolve_audio_mux_inputs(
        self,
        *,
        input_path: str,
        enc_mkv: "Path | None",
        audio_mux_src: Path,
        audio_args: list,
        audio_meta: list[dict],
        tmp_dir: Path,
        run_fn,
        audio_input_args: list | None = None,
    ) -> tuple[list[DVExtractedAudioTrack], list[DVMuxAudioTrack]]:
        """Bereitet Audio-Tracks für MP4Box vor.

        enc_mkv=None: kein MKV vorhanden (Encode direkt nach HEVC).
                      Audio wird sofort aus input_path extrahiert.
        enc_mkv=Path: bestehender Pfad: Audio zuerst aus MKV, Fallback input_path.
        """
        resolved_audio_tracks: list[DVExtractedAudioTrack] = []

        if enc_mkv is not None:
            resolved_audio_tracks = self._extract_audio_tracks(enc_mkv, tmp_dir, run_fn)

        if not resolved_audio_tracks:
            audio_input_args = list(audio_input_args or [])
            if enc_mkv is not None:
                self._log("DV: Audio aus enc_mkv nicht gefunden – baue Audio-Container aus Quelle.", "warn")
            else:
                self._log("DV: Audio wird direkt aus Originalcontainer extrahiert.", "info")

            rc_audio_src = run_fn(
                [self._ffmpeg_path, "-y", "-loglevel", "error"]
                + audio_input_args
                + ["-i", input_path]
                + audio_args
                + ["-vn", "-sn", "-dn", str(audio_mux_src)],
                allow_error=True,
            )

            if rc_audio_src == 0 and audio_mux_src.exists() and audio_mux_src.stat().st_size > 0:
                resolved_audio_tracks = self._extract_audio_tracks(audio_mux_src, tmp_dir, run_fn)

        mux_tracks = self._align_audio_mux_tracks(audio_meta, resolved_audio_tracks)
        return resolved_audio_tracks, mux_tracks

    def mux_plain_mp4_without_dv(
        self,
        *,
        input_path: str,
        enc_mkv: "Path | None",
        audio_mux_src: Path,
        enc_hevc: Path,
        plain_mp4: Path,
        audio_args: list,
        audio_meta: list[dict],
        audio_tracks: list[DVExtractedAudioTrack],
        tmp_dir: Path,
        run_fn,
        audio_input_args: list | None = None,
    ) -> tuple[bool, list[DVExtractedAudioTrack]]:
        if enc_mkv is not None and not audio_tracks:
            audio_tracks = self._extract_audio_tracks(enc_mkv, tmp_dir, run_fn)

        if not audio_tracks:
            audio_input_args = list(audio_input_args or [])
            rc_audio_src = run_fn(
                [self._ffmpeg_path, "-y", "-loglevel", "error"]
                + audio_input_args
                + ["-i", input_path]
                + audio_args
                + ["-vn", "-sn", "-dn", str(audio_mux_src)],
                allow_error=True,
            )

            if rc_audio_src == 0 and audio_mux_src.exists() and audio_mux_src.stat().st_size > 0:
                audio_tracks = self._extract_audio_tracks(audio_mux_src, tmp_dir, run_fn)

        mux_tracks = self._align_audio_mux_tracks(audio_meta, audio_tracks)
        ok = self._mp4box_muxer.mux_plain_mp4_without_dv(
            run_fn,
            plain_mp4=plain_mp4,
            enc_hevc=enc_hevc,
            mux_tracks=mux_tracks,
        )
        return ok, audio_tracks

    def _dv_audio_ext(self, codec_name: str) -> str:
        c = (codec_name or "").lower()
        if c == "aac":
            return ".m4a"
        if c in {"eac3", "ec-3"}:
            return ".eac3"
        if c == "ac3":
            return ".ac3"
        if c == "mp3":
            return ".mp3"
        return ".mka"

    def _extract_audio_tracks(
        self,
        src_container: Path,
        tmp_dir: Path,
        run_fn,
    ) -> list[DVExtractedAudioTrack]:
        probe = run_fn(
            [
                self._ffprobe_path,
                "-v", "error",
                "-select_streams", "a",
                "-show_entries", "stream=index,codec_name",
                "-of", "json",
                str(src_container),
            ],
            allow_error=True,
            return_process=True,
            timeout=30,
            label="ffprobe-Audioanalyse",
        )

        if probe is None or getattr(probe, "returncode", 1) != 0:
            return []

        try:
            data = json.loads(getattr(probe, "stdout", "") or "{}")
        except (json.JSONDecodeError, TypeError) as exc:
            self._log(f"⚠️ DV: ffprobe-Audioanalyse konnte nicht geparst werden: {exc}", "warn")
            return []

        out_tracks: list[DVExtractedAudioTrack] = []

        for out_idx, st in enumerate(data.get("streams", [])):
            codec_name = (st.get("codec_name") or "").lower()
            out_file = tmp_dir / f"audio_{out_idx}{self._dv_audio_ext(codec_name)}"

            rc = run_fn(
                [
                    self._ffmpeg_path, "-y", "-loglevel", "error",
                    "-i", str(src_container),
                    "-map", f"0:a:{out_idx}",
                    "-c:a", "copy",
                    str(out_file),
                ],
                allow_error=True,
            )

            if rc == 0 and out_file.exists() and out_file.stat().st_size > 0:
                out_tracks.append(
                    DVExtractedAudioTrack(
                        mux_order=out_idx,
                        stream_index=int(st.get("index", out_idx)),
                        codec_name=codec_name,
                        path=out_file,
                    )
                )

        return out_tracks

    def _align_audio_mux_tracks(
        self,
        audio_meta: list[dict],
        extracted_tracks: list[DVExtractedAudioTrack],
    ) -> list[DVMuxAudioTrack]:
        if len(extracted_tracks) != len(audio_meta):
            self._log(
                f"⚠️ Audio-Metadaten passen nicht zur Audio-Anzahl "
                f"({len(extracted_tracks)} Dateien / {len(audio_meta)} Meta).",
                "warn",
            )

        meta_by_order = {
            int(meta.get("mux_order", idx)): meta
            for idx, meta in enumerate(audio_meta)
        }

        mux_tracks: list[DVMuxAudioTrack] = []
        for track in extracted_tracks:
            meta = meta_by_order.get(track.mux_order)
            if not meta:
                continue
            mux_tracks.append(
                DVMuxAudioTrack(
                    mux_order=track.mux_order,
                    path=track.path,
                    meta=meta,
                )
            )
        return mux_tracks
