# -*- coding: utf-8 -*-
"""Planning for lossless-video AudioMux jobs."""
from __future__ import annotations

import subprocess
from pathlib import Path

from ..core.lang_codes import canonical_lang
from ..core.media_metadata import normalize_video_codec
from ..core.process_runner import subprocess_no_window_kwargs
from ..rules.audio_plan import audio_filter_chain, audio_input_args_for_plan, compute_audio_track_plan
from .media_contract import _audio_codec_family, _subtitle_codec_family
from .media_contract_types import ExpectedAudioTrack, ExpectedMediaContract, ExpectedSubtitleTrack
from .output_probe import probe_output


class AudioMuxPlanService:
    def __init__(self, *, tools) -> None:
        self.tools = tools

    def build_audio_plan(self, media_info):
        return compute_audio_track_plan(
            audio_streams=media_info.audio_streams,
            file_override=None,
            container="mkv",
            apply_language_rules=False,
        )

    @staticmethod
    def build_output_path(src: Path, overwrite_original: bool) -> tuple[Path, Path | None]:
        if overwrite_original:
            final = src if src.suffix.lower() == ".mkv" else src.with_suffix(".mkv")
            if final.exists() and final.resolve() != src.resolve():
                raise RuntimeError(f"Zieldatei existiert bereits und wird nicht überschrieben: {final.name}")
            tmp = src.with_name(f"{src.stem}.__audio_mux_tmp__.mkv")
            n = 1
            while tmp.exists() or tmp.resolve() in {src.resolve(), final.resolve()}:
                tmp = src.with_name(f"{src.stem}.__audio_mux_tmp__{n}.mkv")
                n += 1
            return final, tmp
        out = src.with_name(f"{src.stem}_Audiomux.mkv")
        n = 1
        while out.exists() or out.resolve() == src.resolve():
            out = src.with_name(f"{src.stem}_Audiomux_{n}.mkv")
            n += 1
        return out, None

    def build_ffmpeg_cmd(self, src: str, out: str, plan) -> list[str]:
        cmd = [
            str(self.tools.ffmpeg), "-n", *audio_input_args_for_plan(plan), "-i", src,
            "-map_metadata", "0", "-map_chapters", "0", "-map", "0:v", "-c:v", "copy",
        ]
        for decision in plan:
            chosen, out_idx = decision.stream, decision.out_idx
            cmd += ["-map", f"0:{chosen.index}"]
            if not decision.needs_transcode:
                cmd += [f"-c:a:{out_idx}", "copy"]
                continue
            bitrate_k = max(32, int(decision.target_bitrate / 1000) if decision.target_bitrate else 256)
            cmd += [f"-c:a:{out_idx}", decision.target_codec, f"-b:a:{out_idx}", f"{bitrate_k}k", f"-ac:a:{out_idx}", str(decision.target_channels)]
            chain = audio_filter_chain(decision)
            if chain:
                cmd += [f"-filter:a:{out_idx}", chain]
        cmd += ["-map", "0:s?", "-c:s", "copy", "-map", "0:t?", "-c:t", "copy", "-map", "0:d?", "-c:d", "copy", out]
        return cmd

    def build_expected_contract(self, source_path: str, media_info, plan) -> ExpectedMediaContract:
        primary = getattr(media_info, "primary_video", None)
        audio = tuple(
            ExpectedAudioTrack(
                codec=_audio_codec_family(decision.target_codec),
                channels=max(0, int(decision.target_channels or 0)),
                language=canonical_lang(getattr(decision.stream, "language", None)),
            )
            for decision in plan
        )
        subtitles = tuple(
            ExpectedSubtitleTrack(
                codec=_subtitle_codec_family(getattr(stream, "codec", "")),
                language=canonical_lang(getattr(stream, "language", None)),
                forced=bool(getattr(stream, "forced", False)),
            )
            for stream in (getattr(media_info, "subtitle_streams", None) or [])
        )
        attachment_count = data_count = None
        try:
            probe = probe_output(
                Path(source_path), ffprobe_path=str(self.tools.ffprobe),
                run_process=subprocess.run, no_window_kwargs=subprocess_no_window_kwargs(),
            )
            attachment_count = sum(1 for s in probe.streams if s.get("codec_type") == "attachment")
            data_count = sum(1 for s in probe.streams if s.get("codec_type") == "data")
        except Exception:
            # Video/audio/subtitle remain fail-closed; auxiliary stream counts
            # are enforced whenever source ffprobe can establish them.
            pass
        return ExpectedMediaContract(
            container="mkv",
            video_codec=normalize_video_codec(getattr(primary, "codec", "")),
            video_stream_count=max(1, len(getattr(media_info, "video_streams", None) or [])),
            audio_tracks=audio,
            subtitle_tracks=subtitles,
            min_video_bit_depth=getattr(primary, "bit_depth", None),
            expected_width=getattr(primary, "width", None),
            expected_height=getattr(primary, "height", None),
            attachment_stream_count=attachment_count,
            data_stream_count=data_count,
        )
