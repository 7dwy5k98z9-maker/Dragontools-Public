# -*- coding: utf-8 -*-
"""Planning for lossless-video AudioMux jobs."""
from __future__ import annotations

from pathlib import Path
from ..core.output_timestamps import build_output_timestamp_args

from ..core.lang_codes import canonical_lang
from ..core.media_metadata import normalize_video_codec
from ..core.process_runner import subprocess_no_window_kwargs
from .tool_runner import run_tool
from ..rules.audio_plan import (
    audio_filter_chain,
    audio_input_args_for_plan,
    compute_audio_track_plan,
    output_default_for_decision,
)
from .media_contract import _audio_codec_family, _subtitle_codec_family
from .media_contract_types import ExpectedAudioTrack, ExpectedMediaContract, ExpectedSubtitleTrack
from .output_probe import probe_output
from .audio_metadata_args import audio_metadata_args, audio_output_title, audio_output_forced


class AudioMuxPlanService:
    def __init__(self, *, tools, worker=None) -> None:
        self.tools = tools
        self.worker = worker
        self.expected_chapter_count = None

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
            else:
                bitrate_k = max(32, int(decision.target_bitrate / 1000) if decision.target_bitrate else 256)
                cmd += [f"-c:a:{out_idx}", decision.target_codec, f"-b:a:{out_idx}", f"{bitrate_k}k", f"-ac:a:{out_idx}", str(decision.target_channels)]
                chain = audio_filter_chain(decision)
                if chain:
                    cmd += [f"-filter:a:{out_idx}", chain]
            cmd += audio_metadata_args(decision)
        cmd += ["-map", "0:s?", "-c:s", "copy", "-map", "0:t?", "-c:t", "copy", "-map", "0:d?", "-c:d", "copy", *build_output_timestamp_args(out), out]
        return cmd

    def build_expected_contract(self, source_path: str, media_info, plan) -> ExpectedMediaContract:
        primary = getattr(media_info, "primary_video", None)
        audio = tuple(
            ExpectedAudioTrack(
                codec=_audio_codec_family(decision.target_codec),
                channels=max(0, int(decision.target_channels or 0)),
                language=canonical_lang(getattr(decision.stream, "language", None)),
                default=output_default_for_decision(decision),
                title=audio_output_title(decision),
                forced=audio_output_forced(decision),
            )
            for decision in plan
        )
        subtitles = tuple(
            ExpectedSubtitleTrack(
                codec=_subtitle_codec_family(getattr(stream, "codec", "")),
                language=canonical_lang(getattr(stream, "language", None)),
                forced=bool(getattr(stream, "forced", False)),
                default=bool(getattr(stream, "default", False)),
                title=str(getattr(stream, "title", "") or ""),
            )
            for stream in (getattr(media_info, "subtitle_streams", None) or [])
        )
        probe = probe_output(
            Path(source_path), ffprobe_path=str(self.tools.ffprobe),
            run_process=self.run_source_probe, no_window_kwargs=subprocess_no_window_kwargs(),
        )
        if not any(stream.get("codec_type") == "video" for stream in probe.streams):
            raise RuntimeError("AudioMux-Quellprobe enthält keinen Videostream.")
        self.expected_chapter_count = len(getattr(probe, 'chapters', ()) or ())
        attachment_count = sum(1 for stream in probe.streams if stream.get("codec_type") == "attachment"
                               or bool((stream.get('disposition') or {}).get('attached_pic', 0)))
        data_count = sum(1 for stream in probe.streams if stream.get("codec_type") == "data")
        return ExpectedMediaContract(
            container="mkv",
            video_codec=normalize_video_codec(getattr(primary, "codec", "")),
            video_stream_count=max(1, len(getattr(media_info, "video_streams", None) or [])),
            audio_tracks=audio,
            subtitle_tracks=subtitles,
            min_video_bit_depth=getattr(primary, "bit_depth", None),
            require_hdr=bool(getattr(media_info, "is_hdr", False)),
            require_dolby_vision=bool(getattr(media_info, "has_dv", False)),
            expected_dolby_vision_profile=(int(getattr(media_info, "dv_profile_major", 0) or 0) or None),
            require_hdr10plus=bool(getattr(media_info, "has_hdrplus", False)),
            expected_width=getattr(primary, "width", None),
            expected_height=getattr(primary, "height", None),
            attachment_stream_count=attachment_count,
            data_stream_count=data_count,
        )

    def run_source_probe(self, command, **_kwargs):
        result = run_tool(command, label="AudioMux Quellprobe", timeout_s=10,
            worker=self.worker, abort_on_request=True,
            log=getattr(self.worker, "log_line", None))
        if result.aborted or result.timed_out:
            raise RuntimeError("AudioMux-Quellprobe wurde abgebrochen oder hat das Zeitlimit überschritten.")
        return result
